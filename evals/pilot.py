"""Release approved development cases and score observed runs without model credentials.

This command copies reviewed decisions; it never runs a model, supplies answers to a
system, approves analysis, or converts inspected examples into held-out data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from evals.contracts import Evidence, digest
from evals.pilot_cases import (
    Disclosure,
    FieldAnswer,
    PilotCase,
    PilotRun,
    PilotSuite,
    SelectionAnswer,
    compare_pilot,
    evidence_exists,
)

DEFAULT_DRAFT = Path(__file__).parent / "review_drafts/pancreatic-pilot"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def checked_file(root: Path, name: str) -> Path:
    path = root / name
    if (
        Path(name).is_absolute()
        or ".." in Path(name).parts
        or not path.resolve().is_relative_to(root.resolve())
    ):
        raise ValueError(f"Unsafe release path: {name}")
    current = root.resolve()
    for part in Path(name).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Linked release path: {name}")
    if not path.is_file():
        raise ValueError(f"Missing release file: {name}")
    return path


def assemble_pilot(draft: Path) -> tuple[PilotSuite, dict[str, bytes]]:
    manifest_bytes = checked_file(draft, "evidence_manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)["files"]
    for name, expected in manifest.items():
        if sha256(checked_file(draft, name).read_bytes()) != expected:
            raise ValueError(f"Reviewed evidence changed: {name}")

    def read(name):
        return json.loads(checked_file(draft, name).read_text())

    cell = read("annotations/GSE273398.json")
    mixed = read("annotations/GSE262627.json")
    excluded = read("annotations/exclusions.json")
    sources = {Path(name).stem: read(name) for name in manifest if name.startswith("sources/")}
    public: dict[str, bytes] = {"sources.json": json_bytes(sources)}
    # Only fetched count-list/filter observations and a literal table header are public.
    # Derived coverage, review assessments, annotations and the audit stay private.
    for name in manifest:
        if name.startswith("evidence/") and Path(name).name in {
            "count_listing.json",
            "counts_filter.json",
            "counts.json",
            "ncbi_raw_counts.header.tsv",
        }:
            public[name] = checked_file(draft, name).read_bytes()
    public["run.schema.json"] = json_bytes(PilotRun.model_json_schema())
    public["INSTRUCTIONS.md"] = (
        b"# Development task inputs\n\n"
        b"Use only this public folder and the equally supplied raw cache. Never access "
        b"private answers or review files.\n"
        b"The stage is part of each task: discovery returns eligible candidates; "
        b"selection inspects sources and returns sample IDs, fields, evidence and limitations.\n"
        b"This is a fixed candidate pool, not live-search recall. Not every acceptable "
        b"study must be returned.\n"
        b"Field names: experimental_model, model_identifier, treatment, time_label. Cite "
        b"complete literal sample field values.\n"
        b"Use canonical experimental_model values: cell_line, patient_derived_organoid, "
        b"patient_tissue, or null for unresolved. Preserve literal source values for "
        b"model_identifier, treatment and time_label. Include applicable known fields "
        b"for selected samples; do not invent missing fields.\n"
        b"Preserve uncertainty and literal identifiers. Selection is not analysis "
        b"approval. Do not invent measurements.\n"
        b"Use run.schema.json to capture the actual response with the exact task/source "
        b"hashes and measured conditions.\n"
        b"The same model, source/Python access, time/token budgets and first-attempt "
        b"policy apply to both arms.\n"
        b"A baseline may use ordinary code but must not import specialist or evaluation "
        b"implementation.\n"
    )
    source_hashes = {name: sha256(data) for name, data in public.items()}
    pack_hash = digest(source_hashes)

    def answer(gse: str, gsm: str, field: str, value: str, quote: str, aliases=()):
        item = Evidence(gse=gse, gsm=gsm, field=field, quote=quote)
        if not evidence_exists(item, sources):
            raise ValueError(f"Reviewed field lacks exact source support: {gse}/{gsm}/{value}")
        return FieldAnswer(value=value, aliases=list(aliases), evidence=[item])

    cell_fields = {}
    for label, group in cell["sample_groups"].items():
        for gsm in group["sample_ids"]:
            cell_fields[gsm] = {
                "experimental_model": answer(
                    "GSE273398",
                    gsm,
                    "characteristics_ch1",
                    cell["experimental_model"],
                    "cell line: PATU8988",
                ),
                "model_identifier": answer(
                    "GSE273398", gsm, "characteristics_ch1", "PATU8988", "cell line: PATU8988"
                ),
                "treatment": answer(
                    "GSE273398", gsm, "characteristics_ch1", label, f"treatment: {label}"
                ),
            }
    if not cell["acceptable_search_result"] or len(cell_fields) != 6:
        raise ValueError("Cell-line selection approvals are incomplete")
    cell_answer = SelectionAnswer(sample_ids=sorted(cell_fields), fields=cell_fields)
    expected = mixed["stage_expectations"]["after_data_inspection"]
    selected = expected["supported_organoid_sample_ids"]
    narrow = mixed["prompt_specific_expectations"]["organoid_only"]
    if selected != narrow["selected_sample_ids"] or len(selected) != 35:
        raise ValueError("Broad/narrow approved organoid subsets differ")
    if not narrow["matches"] or cell["prompt_specific_expectations"]["organoid_only"]["matches"]:
        raise ValueError("Organoid-only prompt distinction changed")
    pdo_defined = any(
        "patient-derived organoids (PDOs)" in text
        for text in sources["GSE262627"]["fields"]["summary"]
    )
    if not pdo_defined:
        raise ValueError("PDO aliases require this source's explicit definition")
    organoid_fields = {}
    for gsm in selected:
        review = mixed["sample_reviews"][gsm]
        if (
            review["status"] != "user_approved"
            or review["final_model"] != "patient_derived_organoid"
        ):
            raise ValueError(f"Sample is not an approved organoid: {gsm}")
        model, time = review["reported_model_identifier"], review["reported_time_point"]
        organoid_fields[gsm] = {
            "experimental_model": answer(
                "GSE262627",
                gsm,
                "characteristics_ch1",
                review["final_model"],
                "cell type: Patient derived organoids of pancreatic cancer",
                ("PDO", "patient-derived organoid"),
            ),
            "model_identifier": answer(
                "GSE262627", gsm, "characteristics_ch1", model, f"cell line: {model}"
            ),
            "time_label": answer("GSE262627", gsm, "characteristics_ch1", time, f"time: {time}"),
        }
    unresolved = [
        gsm for gsm, row in mixed["sample_reviews"].items() if row["status"] == "needs_review"
    ]
    if len(unresolved) != 28 or any(
        mixed["sample_reviews"][g]["final_model"] is not None for g in unresolved
    ):
        raise ValueError("The 28 unresolved model assignments must remain unresolved")
    uncovered = [row["sample_id"] for row in expected["uncovered_organoid_samples"]]
    header = (
        checked_file(draft, "evidence/GSE262627/ncbi_raw_counts.header.tsv")
        .read_text()
        .strip()
        .split("\t")[1:]
    )
    if len(uncovered) != 5 or not set(selected) <= set(header) or set(uncovered) & set(header):
        raise ValueError("Approved subset does not match saved count-header evidence")
    mixed_answer = SelectionAnswer(
        sample_ids=selected,
        fields=organoid_fields,
        unresolved_sample_ids=unresolved,
        disclosures=[
            Disclosure(gse="GSE262627", kind="not_in_count_header", sample_ids=uncovered),
            Disclosure(gse="GSE262627", kind="unresolved_model", sample_ids=unresolved),
        ],
    )
    accepted = ["GSE273398", "GSE262627"]
    if len(excluded) != 6 or any(row["eligible"] is not False for row in excluded):
        raise ValueError("Approved six-study eligibility exclusions changed")
    pool = sorted([*accepted, *(row["gse"] for row in excluded)])
    if set(pool) != set(sources):
        raise ValueError("Reviewed pool and source pack differ")
    constraints = {
        "organism": "human",
        "assay": "bulk RNA-seq",
        "counts_source": "NCBI-generated",
        "min_datasets": 1,
        "max_datasets": 20,
    }
    refs = [
        "annotations/GSE273398.json",
        "annotations/GSE262627.json",
        "annotations/exclusions.json",
    ]
    broad = mixed["stage_expectations"]["search"]["question"]
    suite = PilotSuite(
        input_pack_sha256=pack_hash,
        review_manifest_sha256=sha256(manifest_bytes),
        cases=[
            PilotCase(
                id="pancreatic-discovery",
                stage="discovery",
                prompt=broad,
                constraints=constraints,
                candidate_gses=pool,
                acceptable_gses=accepted,
                review_references=refs,
                scope=(
                    "Acceptable candidates in a fixed reviewed pool; neither positive "
                    "is mandatory in every bounded answer."
                ),
            ),
            PilotCase(
                id="pancreatic-selection",
                stage="selection",
                prompt=broad,
                constraints=constraints,
                candidate_gses=pool,
                acceptable_gses=accepted,
                selections={"GSE273398": cell_answer, "GSE262627": mixed_answer},
                review_references=refs,
                scope=(
                    "Post-inspection selection and approved fields; "
                    "no numeric matrix or downstream approval."
                ),
            ),
            PilotCase(
                id="pancreatic-organoid-selection",
                stage="selection",
                prompt=narrow["prompt"],
                constraints={**constraints, "experimental_model": "patient-derived organoid"},
                candidate_gses=pool,
                acceptable_gses=["GSE262627"],
                selections={"GSE262627": mixed_answer},
                review_references=refs,
                scope=(
                    "Exactly the approved count-covered organoid subset when selected; "
                    "exclusions and uncertainty disclosed."
                ),
            ),
        ],
        pending=read("review_manifest.json")["pending"],
    )
    suite.pending = [p for p in suite.pending if "Integration into runnable" not in p]
    suite.pending += [
        "Independent held-out families and matched model runs",
        "Single-study biological reference and cross-study scientific validation",
        "Review executable instructions and equal-access conditions before the first measured run",
    ]
    return suite, public


def build_release(draft: Path, output: Path) -> PilotSuite:
    suite, public = assemble_pilot(draft)
    public["tasks.json"] = json_bytes(
        [
            {
                **case.public_task(),
                "prompt_sha256": case.prompt_hash(),
                "source_pack_sha256": suite.input_pack_sha256,
            }
            for case in suite.cases
        ]
    )
    all_files = {f"public/{name}": data for name, data in public.items()}
    all_files["private/suite.json"] = json_bytes(suite.model_dump())
    release = {
        "suite": suite.id,
        "scope": "development only",
        "files": {n: sha256(b) for n, b in all_files.items()},
        "input_pack_sha256": suite.input_pack_sha256,
        "review_manifest_sha256": suite.review_manifest_sha256,
    }
    output.mkdir(parents=True, exist_ok=False)
    for name, data in {**all_files, "release.json": json_bytes(release)}.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
    return suite


def load_release(output: Path) -> tuple[PilotSuite, dict]:
    release = json.loads(checked_file(output, "release.json").read_text())
    for name, expected in release["files"].items():
        if sha256(checked_file(output, name).read_bytes()) != expected:
            raise ValueError(f"Released file changed: {name}")
    suite = PilotSuite.model_validate_json(checked_file(output, "private/suite.json").read_text())
    if suite.input_pack_sha256 != release["input_pack_sha256"]:
        raise ValueError("Source pack identity differs")
    public_inputs = {
        name.removeprefix("public/"): expected
        for name, expected in release["files"].items()
        if name.startswith("public/") and name != "public/tasks.json"
    }
    if digest(public_inputs) != suite.input_pack_sha256:
        raise ValueError("Public input hashes do not match the frozen source pack")
    return suite, json.loads(checked_file(output, "public/sources.json").read_text())


def render_report(result: dict) -> str:
    lines = [
        "# Development pilot results",
        "",
        result["scope"],
        "",
        f"Paired development comparison ready: {result['paired_development_ready']}",
        "Scientific / held-out benchmark ready: false",
        "",
        result["note"],
        "",
        "| Stage / arm | Runs observed | Tasks passed | Cases with errors |",
        "| --- | --- | --- | --- |",
    ]
    for key, row in result["summaries"].items():

        def show(name, row=row):
            value = row[name]
            return f"{value['numerator']}/{value['denominator']}" if value["denominator"] else "N/A"

        lines.append(
            f"| {key} | {show('coverage')} | {show('task_completion')} | "
            f"{row['cases_with_errors']} |"
        )
    lines += ["", "## Missing conditions and failures", ""]
    lines += [f"- {error}" for error in result["pairing_errors"]]
    for row in result["cases"]:
        issues = row["errors"] + row["incomplete"]
        lines.append(
            f"- {row['case_id']} / {row['system']}: "
            + ("; ".join(issues) or "No recorded failures")
        )
    lines += ["", "## Still pending", "", *[f"- {p}" for p in result["pending"]], ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("output", type=Path)
    build.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    validate = commands.add_parser("validate")
    validate.add_argument("release", type=Path)
    compare = commands.add_parser("compare")
    compare.add_argument("release", type=Path)
    compare.add_argument("output", type=Path)
    compare.add_argument("records", type=Path, nargs="+")
    compare.add_argument(
        "--raw-output",
        type=Path,
        action="append",
        default=[],
        help="Original saved response file; repeat for each attempt (never the gold answer)",
    )
    args = parser.parse_args()
    if args.command == "build":
        suite = build_release(args.draft, args.output)
        print(
            f"Released {len(suite.cases)} development cases; no model run or scientific approval."
        )
    else:
        suite, sources = load_release(args.release)
        if args.command == "validate":
            print(
                f"Valid release: {len(suite.cases)} development cases. "
                f"{len(suite.pending)} dependencies remain."
            )
            return
        result = compare_pilot(
            suite,
            sources,
            [PilotRun.model_validate_json(p.read_text()) for p in args.records],
            raw_output_hashes={sha256(p.read_bytes()) for p in args.raw_output},
        )
        report = args.output.with_suffix(".md")
        if args.output == report or args.output.exists() or report.exists():
            raise ValueError("Use a new .json output path; existing reports are preserved")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as stream:
            stream.write(json_bytes(result))
        with report.open("x") as stream:
            stream.write(render_report(result))
        print(f"Saved development results to {args.output} and {report}")


if __name__ == "__main__":
    main()
