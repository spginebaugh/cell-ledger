"""The pipeline after the user's last click: ready datasets are designed by the scripted
Claude, runs start on their own, and the comparison follows once every run is done."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from cell_ledger.geo.fetch import FileRecord
from cell_ledger_api.agent.design import compile_design
from cell_ledger_api.db import Database
from cell_ledger_api.pipeline import comparison_name, design_request

from .conftest import LOCAL_DB_URL, ApiFactory
from .test_agent import RECORD, ScriptedTurns, labels, message
from .test_runs import FAKE

COUNTS = gzip.compress(b"GeneID\tGSM1\tGSM2\tGSM3\tGSM4\tGSM5\tGSM6\n1\t5\t6\t7\t8\t9\t10\n")


def plant_session(pg: Callable[..., Any], question: str, state: dict[str, Any]) -> str:
    sid = hashlib.md5(f"{question}{time.time_ns()}".encode()).hexdigest()
    pg(
        "insert into sessions (id, question, state) values ($1, $2, $3::jsonb)",
        sid,
        question,
        json.dumps(state),
    )
    return sid


def plant_ready(pg: Callable[..., Any], tmp_path: Path, sid: str, gse: str) -> None:
    """A collected dataset row with its counts on disk, as a finished download leaves it."""
    local = tmp_path / "sessions" / sid / "geo" / gse
    local.mkdir(parents=True)
    (local / "counts.tsv.gz").write_bytes(COUNTS)
    counts = FileRecord(
        name="counts.tsv.gz",
        url="https://example.test/counts",
        md5=hashlib.md5(COUNTS).hexdigest(),
        bytes=len(COUNTS),
        downloaded_at=datetime.now(UTC),
    )
    record = RECORD.model_copy(update={"gse": gse, "files": {"counts": counts}})
    pg(
        "insert into datasets (session_id, gse, status, record, finished_at) "
        "values ($1, $2, 'ready', $3::jsonb, now())",
        sid,
        gse,
        record.model_dump_json(),
    )


def wait_designed(client: TestClient, sid: str, timeout: float = 15) -> list[dict]:  # type: ignore[type-arg]
    deadline = time.monotonic() + timeout
    while True:
        ds = client.get(f"/api/sessions/{sid}/datasets").json()
        if ds and all(
            d["design_status"] not in ("pending", "designing") for d in ds if d["status"] == "ready"
        ):
            return ds
        assert time.monotonic() < deadline, ds
        time.sleep(0.05)


def wait_comparison(client: TestClient, sid: str, timeout: float = 120) -> dict:  # type: ignore[type-arg]
    deadline = time.monotonic() + timeout
    while True:
        cs = client.get(f"/api/sessions/{sid}/comparisons").json()
        if cs and cs[0]["status"] != "running":
            return cs[0]
        assert time.monotonic() < deadline, cs
        time.sleep(0.2)


STATE = {
    "discovery": {"interpretation": "psoriasis lesional vs healthy skin", "genes": ["IL17A"]},
    "answers": "use healthy donors as the control",
    "genes": ["IL17A"],
}


def test_design_request_carries_what_discovery_settled() -> None:
    req = design_request("Is IL17A up in psoriasis?", STATE)
    assert req.question == "Is IL17A up in psoriasis?" and req.genes == ["IL17A"]
    assert req.context is not None
    assert "two-group comparison: psoriasis lesional vs healthy skin" in req.context
    assert "Clarifications from the user: use healthy donors" in req.context
    assert design_request(None, None).context is None
    # An empty selection is the user's choice; only a missing one falls back to discovery.
    assert design_request("the question", {**STATE, "genes": []}).genes == []
    assert design_request("the question", {"discovery": {"genes": ["GPC3"]}}).genes == ["GPC3"]
    assert comparison_name("Is IL17A higher in psoriasis lesional skin?!") == (
        "is_il17a_higher_in_psoriasis_lesional_skin"
    )
    assert comparison_name("???") == "pooled"


def test_ready_datasets_run_and_compare_on_their_own(
    api: ApiFactory,
    pg: Callable[..., Any],
    tmp_path: Path,
    wait_runs: Callable[..., list[dict]],  # type: ignore[type-arg]
) -> None:
    sid = plant_session(pg, "Is IL17A higher in psoriasis lesional skin?", STATE)
    plant_ready(pg, tmp_path, sid, "GSE100001")
    plant_ready(pg, tmp_path, sid, "GSE100002")
    # One scripted design per dataset; both records carry the same GSMs so order is moot.
    # The first dataset's design needs the validator's second try, as in production.
    turns = ScriptedTurns(
        message([{"type": "text", "text": labels({"GSM1": ["not in record"]}).model_dump_json()}]),
        message([{"type": "text", "text": labels({}).model_dump_json()}]),
        message([{"type": "text", "text": labels({}).model_dump_json()}]),
    )
    # Booting the app is the trigger: recovery designs every ready dataset without a design,
    # exactly as the dataset-finished hook does after a download.
    with api(turn=turns, run_command=FAKE, run_timeout_minutes=0.5) as c:
        ds = wait_designed(c, sid)
        assert [d["design_status"] for d in ds] == ["designed", "designed"]
        for d in ds:
            p = d["proposal"]
            assert p["problems"] == [] and p["design"]["contrasts"][0]["status"] == "confirmed"
            assert p["decisions"] and d["design_error"] is None
        assert sorted(d["proposal"]["attempts"] for d in ds) == [1, 2]
        # Claude saw the question, discovery's reading of it and the clarification.
        first = turns.requests[0]["messages"][0]["content"]
        assert "Is IL17A higher" in first and "Clarifications from the user" in first

        runs = wait_runs(c, sid, timeout=60)
        assert [(r["gse"], r["status"]) for r in runs] == [
            ("GSE100001", "complete"),
            ("GSE100002", "complete"),
        ]
        view = c.get(f"/api/sessions/{sid}/runs/GSE100001/lesional_vs_healthy").json()
        assert view["design"]["genes"] == ["IL17A"]

        cmp = wait_comparison(c, sid)
        assert cmp["name"] == "is_il17a_higher_in_psoriasis_lesional_skin"
        req = cmp["request"]
        assert [m["gse"] for m in req["members"]] == ["GSE100001", "GSE100002"]
        assert req["case_label"] == "psoriasis lesional skin" and req["min_studies"] == 2
        assert req["genes_of_interest"] == ["IL17A"]
        # The fake pipeline writes no DE tables, so the honest verdict is insufficient; what
        # matters here is that it ran without anyone asking for it, exactly once.
        assert cmp["status"] == "insufficient", cmp["error"]
        assert len(c.get(f"/api/sessions/{sid}/comparisons").json()) == 1


def test_unrunnable_contrast_is_skipped_and_counted_as_settled(
    api: ApiFactory, pg: Callable[..., Any], tmp_path: Path
) -> None:
    sid = plant_session(pg, "lesional vs healthy", STATE)
    plant_ready(pg, tmp_path, sid, "GSE100001")
    plant_ready(pg, tmp_path, sid, "GSE100002")
    thin = labels({}).model_copy(deep=True)
    thin.contrast.case_gsms = ["GSM1", "GSM2"]  # two per arm: below the floor
    thin.contrast.control_gsms = ["GSM4", "GSM5"]
    turns = ScriptedTurns(
        message([{"type": "text", "text": thin.model_dump_json()}]),
        message([{"type": "text", "text": thin.model_dump_json()}]),
    )
    with api(turn=turns, run_command=FAKE) as c:
        ds = wait_designed(c, sid)
        assert [d["design_status"] for d in ds] == ["skipped", "skipped"]
        assert all("fewer than 3 samples per group" in d["design_error"] for d in ds)
        assert all(d["proposal"]["problems"] for d in ds)
        time.sleep(0.3)
        assert c.get(f"/api/sessions/{sid}/runs").json() == []
        assert c.get(f"/api/sessions/{sid}/comparisons").json() == []


def test_without_claude_the_design_fails_and_says_why(
    api: ApiFactory, pg: Callable[..., Any], tmp_path: Path
) -> None:
    sid = plant_session(pg, "lesional vs healthy", STATE)
    plant_ready(pg, tmp_path, sid, "GSE100001")
    with api(run_command=FAKE) as c:
        (d,) = wait_designed(c, sid)
        assert d["design_status"] == "failed" and d["proposal"] is None
        assert "Claude is not configured" in d["design_error"]


def plant_finished_run(
    pg: Callable[..., Any], sid: str, gse: str, *, status: str = "complete", attempts: int = 0
) -> None:
    """A run row with one contrast in ``status``; ``running`` rows stand for an interrupted run."""
    proposal, errors = compile_design(RECORD.model_copy(update={"gse": gse}), labels({}), ["IL17A"])
    assert proposal is not None and not errors
    design = proposal.design.model_dump_json()
    run_status = "running" if status == "running" else "finished"
    pg(
        "insert into datasets (session_id, gse, status, record, design_status, finished_at) "
        "values ($1, $2, 'ready', $3::jsonb, 'designed', now())",
        sid,
        gse,
        RECORD.model_copy(update={"gse": gse}).model_dump_json(),
    )
    pg(
        "insert into runs (session_id, gse, status, design, attempts, finished_at) "
        "values ($1, $2, $3, $4::jsonb, $5, case when $3 = 'finished' then now() end)",
        sid,
        gse,
        run_status,
        design,
        attempts,
    )
    pg(
        "insert into run_contrasts (session_id, gse, contrast, status, design, finished_at) "
        "values ($1, $2, 'lesional_vs_healthy', $3, $4::jsonb, "
        "case when $3 <> 'running' then now() end)",
        sid,
        gse,
        status,
        design,
    )


def test_design_is_claimed_once(pg: Callable[..., Any], tmp_path: Path) -> None:
    """Two jobs reaching one ready dataset: the second finds it taken and does nothing."""
    sid = plant_session(pg, "q", STATE)
    plant_ready(pg, tmp_path, sid, "GSE100001")

    async def claims() -> tuple[bool, bool, list[tuple[str, str]]]:
        db = await Database.connect(LOCAL_DB_URL)
        try:
            first = await db.claim_design(sid, "GSE100001")
            second = await db.claim_design(sid, "GSE100001")
            # At boot nothing is in flight, so a stale claim is released and re-queued.
            released = [
                (r["session_id"], r["gse"])
                for r in await db.undesigned_datasets()
                if r["session_id"] == sid
            ]
            return first, second, released
        finally:
            await db.close()

    first, second, released = asyncio.run(claims())
    assert first is True and second is False
    assert released == [(sid, "GSE100001")]


def test_restart_between_last_run_and_its_hook_still_compares(
    api: ApiFactory, pg: Callable[..., Any]
) -> None:
    """Both runs finished, the process died before the hook: boot settles the session."""
    sid = plant_session(pg, "lesional vs healthy", STATE)
    plant_finished_run(pg, sid, "GSE100001")
    plant_finished_run(pg, sid, "GSE100002")
    with api(run_command=FAKE) as c:
        cmp = wait_comparison(c, sid)
        assert [m["gse"] for m in cmp["request"]["members"]] == ["GSE100001", "GSE100002"]
        assert cmp["status"] != "running" and "interrupted" not in (cmp["error"] or "")
        assert len(c.get(f"/api/sessions/{sid}/comparisons").json()) == 1


def test_boot_does_not_fail_the_comparison_it_just_started(
    api: ApiFactory,
    pg: Callable[..., Any],
    wait_runs: Callable[..., list[dict]],  # type: ignore[type-arg]
) -> None:
    """An exhausted run is failed at boot; its hook starts the comparison over the two complete
    runs; the comparison recovery that also runs at boot must not mark it interrupted."""
    sid = plant_session(pg, "lesional vs healthy", STATE)
    plant_finished_run(pg, sid, "GSE100001")
    plant_finished_run(pg, sid, "GSE100002")
    plant_finished_run(pg, sid, "GSE100003", status="running", attempts=99)
    with api(run_command=FAKE) as c:
        runs = wait_runs(c, sid)
        failed = next(r for r in runs if r["gse"] == "GSE100003")
        assert failed["status"] == "failed" and "restart" in failed["error"]
        cmp = wait_comparison(c, sid)
        assert "interrupted by server restart" not in (cmp["error"] or "")
        assert [m["gse"] for m in cmp["request"]["members"]] == ["GSE100001", "GSE100002"]
