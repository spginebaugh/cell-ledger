"""Contract regressions using approved development answers, never performance results."""

import json
import shutil

import pytest
from pydantic import ValidationError

from evals.contracts import Conditions
from evals.pilot import DEFAULT_DRAFT, assemble_pilot, build_release, load_release, render_report
from evals.pilot_cases import FieldObservation, PilotCase, PilotRun, compare_pilot, score_pilot_case


@pytest.fixture
def pilot():
    suite, public = assemble_pilot(DEFAULT_DRAFT)
    # Tests may construct answers from gold. Evaluated systems never receive that gold.
    suite.data_kind = "synthetic"
    return suite, json.loads(public["sources.json"])


def observation(suite, case, gse):
    selected = case.selections.get(gse)
    return PilotRun(
        case_id=case.id,
        stage=case.stage,
        system="specialist",
        conditions=Conditions(
            model="synthetic-fixture",
            source_access="same frozen inputs",
            execution_access="python",
            time_budget_seconds=60,
            token_budget=100,
            snapshot_sha256=suite.input_pack_sha256,
            prompt_sha256=case.prompt_hash(),
            code_revision="synthetic-test",
        ),
        run_status="complete",
        elapsed_seconds=1,
        input_tokens=10,
        output_tokens=10,
        raw_output_sha256="a" * 64,
        candidate_gses=[gse] if case.stage == "discovery" else [],
        selected_samples={gse: selected.sample_ids.copy()} if selected else {},
        sample_fields={
            gse: {
                gsm: {
                    name: FieldObservation(value=answer.value, evidence=answer.evidence)
                    for name, answer in fields.items()
                }
                for gsm, fields in selected.fields.items()
            }
        }
        if selected
        else {},
        disclosures=[d.model_copy(deep=True) for d in selected.disclosures] if selected else [],
    )


def test_release_separates_source_evidence_from_reviewed_answers(tmp_path):
    output = tmp_path / "release"
    original, _ = assemble_pilot(DEFAULT_DRAFT)
    build_release(DEFAULT_DRAFT, output)
    suite, sources = load_release(output)
    assert suite == original
    assert len(suite.cases) == 3 and len(sources) == 8
    tasks = json.loads((output / "public/tasks.json").read_text())
    assert all("acceptable_gses" not in task and "selections" not in task for task in tasks)
    paths = [str(p.relative_to(output / "public")) for p in (output / "public").rglob("*")]
    assert not any("annotations/" in p or "audit/" in p or "assessment" in p for p in paths)
    assert not (output / "public/evidence/GSE262627/organoid_count_coverage.json").exists()
    assert (output / "public/evidence/GSE262627/ncbi_raw_counts.header.tsv").exists()
    with pytest.raises(FileExistsError):
        build_release(DEFAULT_DRAFT, output)
    (output / "public/tasks.json").write_text("[]")
    with pytest.raises(ValueError, match="Released file changed"):
        load_release(output)


def test_changed_review_material_is_never_silently_released(tmp_path):
    shutil.copytree(DEFAULT_DRAFT, tmp_path / "draft")
    path = tmp_path / "draft/annotations/exclusions.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="Reviewed evidence changed"):
        assemble_pilot(tmp_path / "draft")


@pytest.mark.parametrize("gse", ["GSE273398", "GSE262627"])
def test_discovery_accepts_either_positive_without_sample_explanations(pilot, gse):
    suite, sources = pilot
    case = suite.cases[0]
    run = observation(suite, case, gse)
    result = score_pilot_case(case, run, suite, sources)
    assert result["task_passed"]
    assert result["metrics"]["acceptable_pool_coverage"]["value"] == 0.5
    assert result["metrics"]["field_accuracy"]["value"] is None


def test_empty_failed_or_unknown_results_do_not_pass(pilot):
    suite, sources = pilot
    case = suite.cases[0]
    run = observation(suite, case, "GSE273398")
    for candidates in [[], ["GSE404"], ["GSE333917"], ["GSE273398", "GSE273398"]]:
        changed = run.model_copy(update={"candidate_gses": candidates})
        assert not score_pilot_case(case, changed, suite, sources)["task_passed"]
    run.run_status = "timeout"
    assert not score_pilot_case(case, run, suite, sources)["task_passed"]


def test_organoid_only_rejects_cell_line_but_broad_selection_accepts_it(pilot):
    suite, sources = pilot
    broad = suite.cases[1]
    run = observation(suite, broad, "GSE273398")
    assert score_pilot_case(broad, run, suite, sources)["task_passed"]
    narrow = suite.cases[2]
    run.case_id = narrow.id
    run.conditions.prompt_sha256 = narrow.prompt_hash()
    assert not score_pilot_case(narrow, run, suite, sources)["task_passed"]


@pytest.mark.parametrize(
    "change", ["missing", "uncovered", "duplicate", "undisclosed", "conflict", "invented"]
)
def test_exact_subset_and_disclosures_are_required_after_inspection(pilot, change):
    suite, sources = pilot
    case = suite.cases[2]
    run = observation(suite, case, "GSE262627")
    assert score_pilot_case(case, run, suite, sources)["task_passed"]
    ids = run.selected_samples["GSE262627"]
    if change == "missing":
        ids.pop()
    elif change == "uncovered":
        ids.append("GSM8172719")
    elif change == "duplicate":
        ids.append(ids[0])
    elif change == "undisclosed":
        run.disclosures.pop()
    elif change == "conflict":
        run.sample_fields["GSE262627"]["GSM8172683"] = {
            "experimental_model": FieldObservation(value="cell_line")
        }
    else:
        ids.append("GSM0000000")
    assert not score_pilot_case(case, run, suite, sources)["task_passed"]


def test_source_defined_alias_preserves_pdo_identity_and_time(pilot):
    suite, sources = pilot
    case = suite.cases[2]
    run = observation(suite, case, "GSE262627")
    fields = run.sample_fields["GSE262627"]["GSM8172711"]
    fields["experimental_model"].value = "PDO"
    assert score_pilot_case(case, run, suite, sources)["task_passed"]
    fields["model_identifier"].value = "PDO10"
    assert not score_pilot_case(case, run, suite, sources)["task_passed"]
    fields["model_identifier"].value = "PDO6"
    fields["time_label"].value = "0h"
    assert not score_pilot_case(case, run, suite, sources)["task_passed"]


def test_knockout_is_not_knockdown_and_source_quote_is_required(pilot):
    suite, sources = pilot
    case = suite.cases[1]
    run = observation(suite, case, "GSE273398")
    field = run.sample_fields["GSE273398"]["GSM8427626"]["treatment"]
    field.value = "CLIC1-knockout"
    assert not score_pilot_case(case, run, suite, sources)["task_passed"]
    field.value = "CLIC1-knockdown"
    field.evidence = []
    assert not score_pilot_case(case, run, suite, sources)["task_passed"]


def test_unrelated_literal_quote_does_not_establish_field_support(pilot):
    suite, sources = pilot
    case = suite.cases[1]
    run = observation(suite, case, "GSE273398")
    fields = run.sample_fields["GSE273398"]["GSM8427626"]
    fields["treatment"].evidence = fields["model_identifier"].evidence
    result = score_pilot_case(case, run, suite, sources)
    assert not result["task_passed"]
    assert any("Supporting quote needs review" in issue for issue in result["incomplete"])


def test_unreviewed_extra_claim_cannot_be_silently_certified(pilot):
    suite, sources = pilot
    case = suite.cases[1]
    run = observation(suite, case, "GSE273398")
    fields = run.sample_fields["GSE273398"]["GSM8427626"]
    fields["donor_independence"] = fields["model_identifier"].model_copy(deep=True)
    result = score_pilot_case(case, run, suite, sources)
    assert not result["task_passed"]
    assert any("Additional field needs review" in issue for issue in result["incomplete"])


def test_paired_result_requires_saved_original_response_evidence(pilot):
    suite, sources = pilot
    runs = []
    for case in suite.cases:
        for system in ("specialist", "baseline"):
            run = observation(suite, case, case.acceptable_gses[0])
            run.system = system
            runs.append(run)
    missing = compare_pilot(suite, sources, runs)
    assert not missing["paired_development_ready"]
    assert all("Original response" in row["incomplete"][-1] for row in missing["cases"])
    result = compare_pilot(suite, sources, runs, raw_output_hashes={"a" * 64})
    assert all(row["task_passed"] for row in result["cases"])
    assert not result["paired_development_ready"]  # Synthetic fixture is never a measured run.
    assert result["input_pack_sha256"] == suite.input_pack_sha256
    assert result["cases"][0]["conditions"]["model"] == "synthetic-fixture"


@pytest.mark.parametrize("value", ["approved", "blocked"])
def test_selection_approval_cannot_be_promoted_to_analysis_verdict(pilot, value):
    suite, sources = pilot
    case = suite.cases[2]
    run = observation(suite, case, "GSE262627")
    run.analysis_readiness = {"GSE262627": value}
    assert not score_pilot_case(case, run, suite, sources)["task_passed"]


def test_stage_and_prompt_identity_cannot_be_relabelled(pilot):
    suite, sources = pilot
    case = suite.cases[0]
    run = observation(suite, case, "GSE273398")
    run.stage = "selection"
    with pytest.raises(ValueError, match="case and stage"):
        score_pilot_case(case, run, suite, sources)
    run.stage = case.stage
    run.conditions.prompt_sha256 = "0" * 64
    with pytest.raises(ValueError, match="prompt/stage/constraints"):
        score_pilot_case(case, run, suite, sources)


@pytest.mark.parametrize("maximum", [1, 20])
def test_shared_dataset_bounds_accept_one_through_twenty(pilot, maximum):
    suite, _ = pilot
    case = suite.cases[0].model_dump()
    case["constraints"]["max_datasets"] = maximum
    assert PilotCase.model_validate(case)


def test_actual_return_count_obeys_the_requested_maximum(pilot):
    suite, sources = pilot
    case = suite.cases[0]
    case.constraints["max_datasets"] = 1
    run = observation(suite, case, "GSE273398")
    run.candidate_gses.append("GSE262627")
    result = score_pilot_case(case, run, suite, sources)
    assert not result["task_passed"]
    assert "Exceeded the requested dataset maximum" in result["errors"]


@pytest.mark.parametrize("maximum", [0, 21, True, "20"])
def test_invalid_dataset_bounds_rejected(pilot, maximum):
    suite, _ = pilot
    case = suite.cases[0].model_dump()
    case["constraints"]["max_datasets"] = maximum
    with pytest.raises(ValidationError, match="Dataset bounds"):
        PilotCase.model_validate(case)


def test_missing_runs_unequal_budgets_and_usage_are_visible(pilot):
    suite, sources = pilot
    case = suite.cases[0]
    run = observation(suite, case, "GSE273398")
    result = compare_pilot(suite, sources, [run])
    assert result["summaries"]["selection/baseline"]["task_completion"]["value"] == 0
    assert not result["paired_development_ready"]
    assert not result["scientific_benchmark_ready"]
    assert "0/2" in render_report(result)
    baseline = run.model_copy(deep=True, update={"system": "baseline"})
    baseline.conditions.token_budget += 1
    result = compare_pilot(suite, sources, [run, baseline])
    assert any("unequal token_budget" in p for p in result["pairing_errors"])
    run.input_tokens = None
    assert score_pilot_case(case, run, suite, sources)["incomplete"]
    with pytest.raises(ValueError, match="duplicate"):
        compare_pilot(suite, sources, [run, run])
