"""The pipeline drives itself once datasets are chosen: ready -> designed -> run -> compared.

Three hooks, no scheduler. When a download ends ready, the dataset is designed (Claude labels
the samples and picks the one contrast, see ``agent/design.py``) and its run starts. When a design
or a run ends, the session is checked: once nothing is pending or running, two or more
complete runs are pooled into one comparison. Every hook is safe to call twice; a restart
re-runs the design of any ready dataset that has none (:meth:`Pipeline.recover`).

What replaces the user at each step is written down rather than asked:

* A dataset the agent cannot design (no Claude, a refusal, unreadable output) is ``failed``.
* A contrast with problems (too few samples per arm, arms contradicting labels, a sample
  whose label the validator rejected) is ``skipped`` with the reasons; the rest proceed.
* A session with one complete run gets no comparison; that run page is the answer.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from cell_ledger.compare import QuerySetMember
from cell_ledger.geo import DatasetRecord
from cell_ledger_api.agent.design import DatasetNotReady, Designer, DesignRequest
from cell_ledger_api.agent.llm import AgentUnavailable, quiet
from cell_ledger_api.compare import (
    CompareRequest,
    CompareService,
    ComparisonConflict,
    MembersNotReady,
)
from cell_ledger_api.designs import RunRequest
from cell_ledger_api.runs import CountsMissing, RunConflict, RunService
from cell_ledger_api.sessions import SessionService

log = logging.getLogger(__name__)


def design_request(question: str | None, state: dict[str, Any] | None) -> DesignRequest:
    """What the agent needs from the session: the question, what discovery settled about it
    (its reading as a two-group comparison, the user's clarifications) and the genes."""
    st = state or {}
    discovery = st.get("discovery") or {}
    context = [
        f"The question as a two-group comparison: {discovery['interpretation']}"
        if discovery.get("interpretation")
        else None,
        f"Clarifications from the user: {st['answers']}" if st.get("answers") else None,
    ]
    # An explicitly empty selection is a choice (the user removed every gene); only a missing
    # one falls back to what discovery read off the question.
    genes = st["genes"] if st.get("genes") is not None else discovery.get("genes") or []
    return DesignRequest(
        question=(question or discovery.get("interpretation") or "see context").strip(),
        context="\n".join(c for c in context if c) or None,
        genes=[str(g) for g in genes],
    )


def comparison_name(question: str, max_len: int = 48) -> str:
    """A slug of the question, cut at a word boundary so the name reads whole."""
    words = re.sub(r"[^a-z0-9]+", "_", question.lower()).strip("_").split("_")
    out: list[str] = []
    for w in words:
        if not w or (out and len("_".join([*out, w])) > max_len):
            break
        out.append(w[:max_len])
    return "_".join(out) or "pooled"


class Pipeline:
    def __init__(
        self,
        sessions: SessionService,
        runs: RunService,
        comparisons: CompareService,
        designer: Designer,
        *,
        max_concurrent_designs: int = 2,
    ) -> None:
        self._sessions = sessions
        self._runs = runs
        self._comparisons = comparisons
        self._designer = designer
        self._db = sessions.db
        self._sem = asyncio.Semaphore(max_concurrent_designs)
        sessions.on_dataset_finished = self.on_dataset_finished
        runs.on_run_finished = self.on_run_finished

    # ------------------------------------------------------------- hooks

    async def on_dataset_finished(self, session_id: str, gse: str, status: str) -> None:
        if status == "ready":
            self._sessions.spawn(self.design(session_id, gse))
        else:
            await self.settle(session_id)

    async def on_run_finished(self, session_id: str) -> None:
        await self.settle(session_id)

    async def recover(self) -> int:
        """Design every ready dataset a restart left undesigned, and settle every session whose
        runs all finished but whose comparison never started (the restart came between the
        last run and its hook). Runs and downloads are re-dispatched by their own services."""
        rows = await self._db.undesigned_datasets()
        for row in rows:
            self._sessions.spawn(self.design(row["session_id"], row["gse"]))
        for session_id in await self._db.sessions_awaiting_comparison():
            await self.settle(session_id)
        return len(rows)

    # ------------------------------------------------------------ design

    async def design(self, session_id: str, gse: str) -> None:
        try:
            await self._design(session_id, gse)
        except Exception:  # a bug here must not stall the session: fail the dataset, move on
            log.exception("design %s/%s crashed", session_id, gse)
            await self._db.finish_design(
                session_id, gse, status="failed", proposal=None, error="internal error"
            )
        await self.settle(session_id)

    async def _design(self, session_id: str, gse: str) -> None:
        # One job per dataset: the claim flips pending -> designing atomically, so a hook and
        # a recovery that both reach the same row cannot both call Claude and race the run.
        if not await self._db.claim_design(session_id, gse):
            return
        row = await self._db.get_dataset(session_id, gse)
        session = await self._db.get_session(session_id)
        if row is None or not row["record"] or session is None:
            await self._db.finish_design(
                session_id, gse, status="failed", proposal=None, error="dataset record missing"
            )
            return
        record = DatasetRecord.model_validate(row["record"])
        req = design_request(session["question"], session["state"])
        try:
            async with self._sem:
                proposal = await self._designer.design(record, req, quiet)
        except (AgentUnavailable, DatasetNotReady) as e:
            await self._db.finish_design(
                session_id, gse, status="failed", proposal=None, error=str(e)
            )
            return
        except Exception as e:  # anthropic errors, network
            log.warning("design %s/%s failed: %s", session_id, gse, e)
            await self._db.finish_design(
                session_id, gse, status="failed", proposal=None, error=f"{type(e).__name__}: {e}"
            )
            return
        dumped = proposal.model_dump(mode="json")
        if proposal.problems:
            await self._db.finish_design(
                session_id,
                gse,
                status="skipped",
                proposal=dumped,
                error="; ".join(proposal.problems),
            )
            return
        try:
            await self._runs.start(session_id, proposal.design)
        except (CountsMissing, RunConflict) as e:
            await self._db.finish_design(
                session_id, gse, status="failed", proposal=dumped, error=str(e)
            )
            return
        await self._db.finish_design(
            session_id, gse, status="designed", proposal=dumped, error=None
        )

    # ----------------------------------------------------------- compare

    async def settle(self, session_id: str) -> None:
        """Start the comparison once the session has nothing left in flight."""
        try:
            await self._settle(session_id)
        except Exception:
            log.exception("settle %s failed", session_id)

    async def _settle(self, session_id: str) -> None:
        datasets = await self._db.list_datasets(session_id)
        if any(
            d["status"] == "pending"
            or (d["status"] == "ready" and d["design_status"] in ("pending", "designing"))
            for d in datasets
        ):
            return
        runs = await self._db.list_run_contrasts(session_id)
        if any(r["status"] == "running" for r in runs):
            return
        complete = [r for r in runs if r["status"] == "complete"]
        if len({r["gse"] for r in complete}) < 2:
            return
        if await self._db.list_comparisons(session_id):
            return  # one comparison per session; it was started by an earlier hook
        session = await self._db.get_session(session_id)
        if session is None:
            return
        state = session["state"] or {}
        discovery = state.get("discovery") or {}
        question = session["question"] or discovery.get("interpretation") or "pooled comparison"
        designs = [RunRequest.model_validate(r["design"]) for r in complete if r["design"]]
        first = designs[0].contrasts[0] if designs else None
        genes: dict[str, None] = {}
        for d in designs:
            genes.update(dict.fromkeys(d.genes))
        members: list[QuerySetMember] = []
        seen: set[str] = set()
        for r in complete:  # one contrast per dataset by construction; keep it that way
            if r["gse"] in seen:
                continue
            seen.add(r["gse"])
            members.append(QuerySetMember(gse=r["gse"], contrast=r["contrast"]))
        req = CompareRequest(
            name=comparison_name(question),
            question=question[:1000],
            case_label=first.case_label if first else "case",
            control_label=first.control_label if first else "control",
            members=members,
            genes_of_interest=list(genes),
            min_studies=2,
        )
        try:
            await self._comparisons.start(session_id, req)
        except (ComparisonConflict, MembersNotReady) as e:
            log.info("comparison for %s not started: %s", session_id, e)
