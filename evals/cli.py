"""Prepare, freeze, capture, score and compare evals without provider credentials."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.contracts import Benchmark, Conditions, RunRecord, Snapshot, prompt_digest
from evals.observations import capture_run
from evals.scoring import compare


def write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def freeze(gold_path: Path, snapshot_path: Path, output: Path) -> None:
    gold = Benchmark.model_validate_json(gold_path.read_text())
    snapshot = Snapshot.model_validate_json(snapshot_path.read_text())
    gold.validate_sources(snapshot)
    if output.exists():
        raise ValueError("Freeze destination exists; create a new benchmark version")
    public_tasks = [
        {
            "id": case.id,
            "prompt": case.prompt,
            "constraints": case.constraints,
            "candidate_gses": list(case.studies),
            "prompt_sha256": prompt_digest(case),
        }
        for case in gold.cases
    ]
    # Neither labels, split assignments nor expected actions enter the model-facing pack.
    write_new(output / "public/tasks.json", public_tasks)
    write_new(output / "public/snapshot.json", snapshot.model_dump())
    write_new(output / "private/gold.json", gold.model_copy(update={"frozen": True}).model_dump())
    write_new(
        output / "release.json",
        {
            "benchmark": gold.id,
            "version": gold.version,
            "snapshot_sha256": snapshot.digest(),
            "public_files": ["public/tasks.json", "public/snapshot.json"],
            "warning": "Give systems only public/ and the same raw cache; never private/.",
        },
    )


def render_report(result: dict) -> str:
    lines = [
        "# Evaluation comparison",
        "",
        f"Benchmark: {result['benchmark']} / {result['version']}",
        f"Data kind: **{result['data_kind']}**",
        "",
        f"Comparison ready: **{result['comparison_ready']}**",
        "",
        result["note"],
        "",
        "| Split / system | Cases observed | P@3 slots | Recall@10 in pool | "
        "Correct bundles | Answerable task completion | Critical errors |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    def fraction(value):
        return f"{value['numerator']}/{value['denominator']}" if value["denominator"] else "N/A (0)"

    for name, summary in result["summaries"].items():
        lines.append(
            f"| {name} | {fraction(summary['case_coverage'])} | "
            f"{fraction(summary['precision_at_3_slots'])} | "
            f"{fraction(summary['recall_at_10_in_pool'])} | "
            f"{fraction(summary['correct_bundle_completion'])} | "
            f"{fraction(summary['answerable_task_completion'])} | "
            f"{summary['critical_error_count']} |"
        )
    lines += ["", "## Pairing problems", ""]
    lines += [f"- {error}" for error in result["pairing_errors"]] or ["None."]
    lines += ["", "## Per-case failures and missing evidence", ""]
    for row in result["cases"]:
        issues = row["critical_errors"] + row["incomplete"]
        lines.append(
            f"- {row['case_id']} / {row['system']}: " + ("; ".join(issues) or "None recorded")
        )
    lines += ["", "No global GEO recall, biological validity, or comparative win is inferred.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build-gold")
    build.add_argument("output", type=Path)
    build.add_argument("workspaces", nargs="+", type=Path)
    check = commands.add_parser("validate")
    check.add_argument("gold", type=Path)
    check.add_argument("snapshot", type=Path)
    lock = commands.add_parser("freeze")
    lock.add_argument("gold", type=Path)
    lock.add_argument("snapshot", type=Path)
    lock.add_argument("output", type=Path)
    capture = commands.add_parser("capture")
    capture.add_argument("bundle", type=Path)
    capture.add_argument("conditions", type=Path)
    capture.add_argument("output", type=Path)
    capture.add_argument("--case", required=True)
    capture.add_argument("--system", choices=["specialist", "baseline"], required=True)
    compare_cmd = commands.add_parser("compare")
    compare_cmd.add_argument("gold", type=Path)
    compare_cmd.add_argument("snapshot", type=Path)
    compare_cmd.add_argument("output", type=Path)
    compare_cmd.add_argument("records", nargs="+", type=Path)
    args = parser.parse_args()
    if args.command == "build-gold":
        from evals.annotations import combine

        gold, snapshot = combine(args.workspaces)
        if args.output.exists():
            raise ValueError("Use a new gold output directory")
        write_new(args.output / "gold.json", gold.model_dump())
        write_new(args.output / "snapshot.json", snapshot.model_dump())
    elif args.command in {"validate", "freeze"}:
        if args.command == "freeze":
            freeze(args.gold, args.snapshot, args.output)
        else:
            gold = Benchmark.model_validate_json(args.gold.read_text())
            gold.validate_sources(Snapshot.model_validate_json(args.snapshot.read_text()))
            print(
                f"Valid: {len(gold.cases)} cases; independent reviewer signoff is still required."
            )
    elif args.command == "capture":
        record = capture_run(
            args.bundle,
            args.case,
            args.system,
            Conditions.model_validate_json(args.conditions.read_text()),
        )
        write_new(args.output, record.model_dump())
    elif args.command == "compare":
        result = compare(
            Benchmark.model_validate_json(args.gold.read_text()),
            Snapshot.model_validate_json(args.snapshot.read_text()),
            [RunRecord.model_validate_json(path.read_text()) for path in args.records],
        )
        write_new(args.output, result)
        report = args.output.with_suffix(".md")
        with report.open("x") as stream:
            stream.write(render_report(result))
        print(f"Saved {args.output} and {report}; comparison ready: {result['comparison_ready']}")


if __name__ == "__main__":
    main()
