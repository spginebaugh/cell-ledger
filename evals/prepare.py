"""Prepare an UNREVIEWED source/annotation workspace. Never invent ground truth."""

import argparse
import asyncio
import csv
from datetime import UTC, datetime
from pathlib import Path

from cell_ledger.geo.cache import CachedClient
from cell_ledger.geo.retrieval import get_series_metadata, search_geo
from evals.cli import write_new
from evals.contracts import Snapshot, SourceRecord


async def prepare(topic: str, output: Path, cache: Path, limit: int):
    if output.exists():
        raise ValueError("Use a new workspace; existing annotations will not be overwritten")
    client = CachedClient(cache)
    hits = await search_geo(client, topic, limit=limit)
    records, errors = {}, []
    for hit in hits:
        try:
            series = await get_series_metadata(client, hit.gse)
            records[hit.gse] = SourceRecord(
                gse=hit.gse,
                url=series.source_url,
                retrieved_at=datetime.now(UTC).isoformat(),
                fields=series.fields,
                samples={sample.gsm: sample.fields for sample in series.samples},
            )
        except (ValueError, TimeoutError) as exc:
            errors.append({"gse": hit.gse, "error": str(exc)})
    snapshot = Snapshot(records=records)
    write_new(output / "public/snapshot.json", snapshot.model_dump())
    write_new(
        output / "public/search.json",
        {
            "topic": topic,
            "limit": limit,
            "hits": [hit.model_dump() for hit in hits],
            "errors": errors,
            "status": "unreviewed",
        },
    )
    write_new(
        output / "private/review.json",
        {
            "status": "draft_not_gold",
            "snapshot_sha256": snapshot.digest(),
            "instructions": "Review source evidence; flag domain questions for Scott. "
            "then create gold using the documented schema. Do not use agent answers as gold.",
        },
    )
    write_new(
        output / "private/case.json",
        {
            "benchmark_id": "cell-ledger-eval",
            "version": "draft-1",
            "case": {
                "id": output.name,
                "prompt": topic,
                "constraints": {"max_datasets": 3},
                "required_workflow": "none",
                "expected_action": None,
                "clarification_targets": [],
                "reviewed_by": "",
                "review_notes": "",
            },
        },
    )
    with (output / "private/studies.csv").open("w") as stream:
        columns = [
            "gse",
            "title",
            "source_url",
            "family_id",
            "split",
            "relevant",
            "eligible",
            "expected_gsms",
            "units",
            "de_ready",
            "rationale",
            "evidence_field",
            "evidence_quote",
            "reviewed_by",
        ]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for source in records.values():
            writer.writerow(
                {
                    "gse": source.gse,
                    "title": " ".join(source.fields.get("title", [])),
                    "source_url": source.url,
                }
            )
    with (output / "private/samples.csv").open("w") as stream:
        columns = [
            "gse",
            "gsm",
            "title",
            "raw_characteristics",
            "include",
            "group",
            "tissue",
            "treatment",
            "time_point",
            "material_type",
            "exclusion_reason",
            "evidence_field",
            "evidence_quote",
            "reviewed_by",
        ]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for source in records.values():
            for gsm, fields in source.samples.items():
                writer.writerow(
                    {
                        "gse": source.gse,
                        "gsm": gsm,
                        "title": " ".join(fields.get("title", [])),
                        "raw_characteristics": " | ".join(fields.get("characteristics_ch1", [])),
                    }
                )
    print(
        f"Prepared {len(records)} UNREVIEWED studies, "
        f"{sum(len(r.samples) for r in records.values())} sample rows; errors: {len(errors)}."
    )
    print(f"Workspace: {output}; snapshot hash: {snapshot.digest()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topic")
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache", type=Path, default=Path("data/geo/cache"))
    parser.add_argument("--limit", type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.limit <= 20:
        parser.error("Use 1-20 candidates per preparation pass")
    asyncio.run(prepare(args.topic, args.output, args.cache, args.limit))
