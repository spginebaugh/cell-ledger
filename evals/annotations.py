"""Convert completed review worksheets to strict gold. Blanks never become guessed labels."""

import csv
import json
from pathlib import Path

from evals.contracts import Benchmark, CaseGold, Evidence, SampleGold, Snapshot, StudyGold


def boolean(value: str, field: str) -> bool:
    if value.strip().lower() not in {"true", "false"}:
        raise ValueError(f"{field}: enter true or false; blank is unreviewed")
    return value.strip().lower() == "true"


def required(value: str, field: str) -> str:
    if not value.strip():
        raise ValueError(f"{field} is unreviewed")
    return value.strip()


def assemble_gold(workspace: Path) -> tuple[Benchmark, Snapshot]:
    snapshot = Snapshot.model_validate_json((workspace / "public/snapshot.json").read_text())
    settings = json.loads((workspace / "private/case.json").read_text())
    with (workspace / "private/studies.csv").open() as stream:
        study_rows = list(csv.DictReader(stream))
    with (workspace / "private/samples.csv").open() as stream:
        sample_rows = list(csv.DictReader(stream))
    ids = [row["gse"] for row in study_rows]
    if len(ids) != len(set(ids)) or set(ids) != set(snapshot.records):
        raise ValueError("Study worksheet must judge every snapshot record exactly once")
    seen_samples = [(row["gse"], row["gsm"]) for row in sample_rows]
    expected_samples = {
        (gse, gsm) for gse, source in snapshot.records.items() for gsm in source.samples
    }
    if len(seen_samples) != len(set(seen_samples)) or set(seen_samples) != expected_samples:
        raise ValueError("Sample worksheet must preserve every source sample exactly once")
    studies = {}
    splits = set()
    for row in study_rows:
        gse = row["gse"]
        relevant, eligible = (
            boolean(row["relevant"], f"{gse}.relevant"),
            boolean(row["eligible"], f"{gse}.eligible"),
        )
        splits.add(required(row["split"], f"{gse}.split"))
        expected_gsms, labels = [], {}
        if relevant and eligible:
            for sample in (s for s in sample_rows if s["gse"] == gse):
                gsm = sample["gsm"]
                required(sample["reviewed_by"], f"{gsm}.reviewed_by")
                if not boolean(sample["include"], f"{gsm}.include"):
                    required(sample["exclusion_reason"], f"{gsm}.exclusion_reason")
                    continue
                expected_gsms.append(gsm)
                fields = {
                    field: None if sample[field] == "UNKNOWN" else sample[field]
                    for field in ("group", "tissue", "treatment", "time_point", "material_type")
                    if sample[field]
                }
                if fields:
                    labels[gsm] = SampleGold(
                        fields=fields,
                        evidence=[
                            Evidence(
                                gse=gse,
                                gsm=gsm,
                                field=required(sample["evidence_field"], f"{gsm}.evidence_field"),
                                quote=required(sample["evidence_quote"], f"{gsm}.evidence_quote"),
                            )
                        ],
                    )
        study_evidence = [
            Evidence(
                gse=gse,
                field=required(row["evidence_field"], f"{gse}.evidence_field"),
                quote=required(row["evidence_quote"], f"{gse}.evidence_quote"),
            )
        ]
        studies[gse] = StudyGold(
            family_id=required(row["family_id"], f"{gse}.family_id"),
            relevant=relevant,
            eligible=eligible,
            expected_gsms=expected_gsms,
            units=row["units"] or None,
            de_ready=boolean(row["de_ready"], f"{gse}.de_ready") if row["de_ready"] else None,
            samples=labels,
            evidence=study_evidence,
            rationale=required(row["rationale"], f"{gse}.rationale"),
            reviewed_by=required(row["reviewed_by"], f"{gse}.reviewed_by"),
        )
    if len(splits) != 1:
        raise ValueError(
            "A case's candidate pool must share one split; split studies across cases instead"
        )
    case = CaseGold(**settings["case"], split=splits.pop(), studies=studies)
    benchmark = Benchmark(
        id=settings["benchmark_id"],
        version=settings["version"],
        data_kind=snapshot.data_kind,
        snapshot_sha256=snapshot.digest(),
        cases=[case],
    )
    benchmark.validate_sources(snapshot)
    return benchmark, snapshot


def combine(workspaces: list[Path]) -> tuple[Benchmark, Snapshot]:
    benchmarks, records = [], {}
    for workspace in workspaces:
        benchmark, snapshot = assemble_gold(workspace)
        benchmarks.append(benchmark)
        for gse, source in snapshot.records.items():
            if gse in records and records[gse] != source:
                raise ValueError(f"Different source snapshots for {gse}; reconcile before freezing")
            records[gse] = source
    first = benchmarks[0]
    if any(
        (b.id, b.version, b.data_kind) != (first.id, first.version, first.data_kind)
        for b in benchmarks
    ):
        raise ValueError("All workspaces must use the same benchmark ID, version and data kind")
    snapshot = Snapshot(data_kind=first.data_kind, records=records)
    benchmark = Benchmark(
        id=first.id,
        version=first.version,
        data_kind=first.data_kind,
        snapshot_sha256=snapshot.digest(),
        cases=[c for b in benchmarks for c in b.cases],
    )
    benchmark.validate_sources(snapshot)
    return benchmark, snapshot
