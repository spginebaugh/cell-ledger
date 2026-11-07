"""Check this draft's evidence and internal consistency; not scientific scoring."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    manifest = read("evidence_manifest.json")["files"]
    for name, expected in manifest.items():
        require(
            hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected,
            f"Evidence changed: {name}",
        )
    cell = read("annotations/GSE273398.json")
    mixed = read("annotations/GSE262627.json")
    source = read("sources/GSE262627.json")
    cell_source = read("sources/GSE273398.json")
    require(len(read("annotations/exclusions.json")) == 6, "Six exclusions required")
    controls = set(cell["sample_groups"]["control"]["sample_ids"])
    knockdown = set(cell["sample_groups"]["CLIC1-knockdown"]["sample_ids"])
    require(
        len(controls) == len(knockdown) == 3 and not controls & knockdown,
        "Treatment groups must be three distinct samples each",
    )
    for sid in controls | knockdown:
        expected = "control" if sid in controls else "CLIC1-knockdown"
        require(
            f"treatment: {expected}" in cell_source["samples"][sid]["characteristics_ch1"],
            f"Treatment source mismatch: {sid}",
        )
    reviews = mixed["sample_reviews"]
    require(
        set(reviews) == set(source["samples"]) and len(reviews) == 68,
        "All 68 samples must be retained",
    )
    organoids = {
        sid for sid, r in reviews.items() if r["final_model"] == "patient_derived_organoid"
    }
    unresolved = {sid for sid, r in reviews.items() if r["status"] == "needs_review"}
    require(len(organoids) == 40 and len(unresolved) == 28, "Incorrect review counts")
    for sid, r in reviews.items():
        fields = source["samples"][sid]["characteristics_ch1"]
        identifier = r.get("reported_model_identifier", r.get("reported_cell_line"))
        require(f"cell line: {identifier}" in fields, f"Identifier changed: {sid}")
        require(f"time: {r['reported_time_point']}" in fields, f"Time changed: {sid}")
        if sid in unresolved:
            require(r["final_model"] is None, f"Unresolved sample assigned: {sid}")
        else:
            require(
                "cell type: Patient derived organoids of pancreatic cancer" in fields,
                f"Organoid source mismatch: {sid}",
            )
    header = (
        (ROOT / "evidence/GSE262627/ncbi_raw_counts.header.tsv").read_text().strip().split("\t")
    )
    coverage = mixed["organoid_subset"]["ncbi_raw_count_coverage"]
    covered = set(coverage["covered_sample_ids"])
    uncovered = {r["sample_id"] for r in coverage["uncovered_samples"]}
    require(covered == organoids & set(header) and len(covered) == 35, "Coverage mismatch")
    require(uncovered == organoids - set(header) and len(uncovered) == 5, "Omissions mismatch")
    selected = set(mixed["prompt_specific_expectations"]["organoid_only"]["selected_sample_ids"])
    require(selected == covered and not selected & unresolved, "Selection mismatch")
    for missing in mixed["absent_time_points"]:
        require(
            not any(
                r.get("reported_model_identifier") == missing["model_identifier"]
                and r["reported_time_point"] == missing["time_label"]
                for r in reviews.values()
            ),
            "Absent time point actually present",
        )
    require(
        cell["acceptable_search_result"] is True
        and cell["prompt_specific_expectations"]["organoid_only"]["matches"] is False,
        "Broad and narrow question expectations conflated",
    )
    require(
        "search" in mixed["stage_expectations"]
        and "after_data_inspection" in mixed["stage_expectations"],
        "Stages conflated",
    )
    require(
        "patient-derived organoids (PDOs)" in " ".join(source["fields"]["summary"]),
        "PDO abbreviation lacks source definition",
    )
    require(
        cell["terminology_expectations"]["knockdown_vs_knockout"]["equivalent"] is False,
        "Knockdown/knockout distinction missing",
    )
    print(
        f"PASS: {len(manifest)} file hashes; source-backed groups, identifiers, time labels; "
        "40 organoids / 28 unresolved; 35 covered / 5 uncovered; prompt and stage separation."
    )
    print("This verifies draft consistency, not scientific readiness or app performance.")


if __name__ == "__main__":
    main()
