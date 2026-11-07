"""Run only a public frozen task. No gold labels are accepted by this entry point."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from cell_ledger.geo.cache import CachedClient
from cell_ledger.geo.client import GeoSeriesHit
from cell_ledger.geo.retrieval import get_series_metadata
from cell_ledger.interpretation import Interpreter
from cell_ledger.pipeline import RunRequest, run_pipeline
from evals.contracts import Snapshot, digest


async def run(public: Path, case_id: str, output: Path, cache: Path, model: str | None):
    task = next(
        (t for t in json.loads((public / "tasks.json").read_text()) if t["id"] == case_id), None
    )
    if task is None:
        raise ValueError("Unknown public task ID")
    if "stage" in task:
        raise ValueError(
            "Stage-specific tasks use evals.pilot run records; "
            "this runner accepts legacy frozen bundle tasks only"
        )
    if (
        digest({"prompt": task["prompt"], "constraints": task["constraints"]})
        != task["prompt_sha256"]
    ):
        raise ValueError("Public prompt was modified after freeze")
    snapshot = Snapshot.model_validate_json((public / "snapshot.json").read_text())
    client = CachedClient(cache, offline=True)
    candidates = []
    for gse in task["candidate_gses"]:
        source = snapshot.records[gse]
        if not source.exists:
            continue
        metadata = await get_series_metadata(client, gse)
        if (
            metadata.fields != source.fields
            or {s.gsm: s.fields for s in metadata.samples} != source.samples
        ):
            raise ValueError(f"{gse}: cached metadata differs from the frozen snapshot")
        candidates.append(
            GeoSeriesHit(
                gse=gse,
                title=" ".join(source.fields.get("title", [])),
                summary=" ".join(source.fields.get("summary", [])),
                taxa=sorted(
                    {
                        organism
                        for sample in metadata.samples
                        for organism in sample.values("organism_ch1")
                        if organism
                    }
                ),
                series_types=source.fields.get("type", []),
                published=None,
                pubmed_ids=source.fields.get("pubmed_id", []),
                matched_queries=[],
                n_samples=len(source.samples),
            )
        )
    interpreter = None
    if model:
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError("Scott must configure model credentials before a live model run")
        interpreter = Interpreter(model, key, cache / "interpretations")
    constraints = task["constraints"]
    request = RunRequest(
        topic=task["prompt"],
        offline=True,
        **{
            k: v
            for k, v in constraints.items()
            if k in RunRequest.model_fields and k not in {"topic", "offline"}
        },
    )

    async def ask(gse, options):
        # Preserve the initial ask; do not invent an answer or expose gold to the system.
        print(f"{gse} requires clarification: {options}; recorded without an invented answer")
        return None

    manifest = await run_pipeline(
        request,
        output,
        client,
        interpreter=interpreter,
        candidate_pool=candidates,
        snapshot_sha256=snapshot.digest(),
        ask=ask,
    )
    print(f"{manifest['status']}: {output}")
    print("Without --model this is a deterministic diagnostic, not the Claude baseline comparison.")


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("public", type=Path)
    parser.add_argument("case")
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--model", default=os.getenv("CELL_LEDGER_MODEL"))
    args = parser.parse_args()
    asyncio.run(run(args.public, args.case, args.output, args.cache, args.model))
