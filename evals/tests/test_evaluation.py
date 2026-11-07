import json

import pytest
from pydantic import ValidationError

from evals.cli import freeze, render_report
from evals.contracts import (
    Benchmark,
    BundleObservation,
    CaseGold,
    Conditions,
    Evidence,
    RunRecord,
    SampleGold,
    SamplePrediction,
    Snapshot,
    SourceRecord,
    StudyGold,
    prompt_digest,
)
from evals.scoring import compare, score_case


@pytest.fixture
def fixture():
    evidence = Evidence(
        gse="GSE1", gsm="GSM1", field="characteristics_ch1", quote="condition: treated"
    )
    snapshot = Snapshot(
        data_kind="synthetic",
        records={
            "GSE1": SourceRecord(
                gse="GSE1",
                url="fixture://synthetic/GSE1",
                retrieved_at="fixture",
                fields={"title": ["Synthetic positive"]},
                samples={"GSM1": {"characteristics_ch1": ["condition: treated"]}},
            ),
            "GSE2": SourceRecord(
                gse="GSE2",
                url="fixture://synthetic/GSE2",
                retrieved_at="fixture",
                fields={"title": ["Synthetic mouse trap"]},
            ),
            "GSE999": SourceRecord(
                gse="GSE999",
                exists=False,
                url="fixture://nonexistent",
                retrieved_at="fixture",
                absence_evidence="Synthetic absence fixture",
            ),
        },
    )
    positive = StudyGold(
        family_id="family-a",
        relevant=True,
        eligible=True,
        expected_gsms=["GSM1"],
        units="counts",
        de_ready=False,
        samples={"GSM1": SampleGold(fields={"group": "case"}, evidence=[evidence])},
        rationale="Synthetic positive",
        reviewed_by="synthetic-reviewer",
        evidence=[Evidence(gse="GSE1", field="title", quote="Synthetic positive")],
    )
    trap = StudyGold(
        family_id="family-b",
        relevant=True,
        eligible=False,
        rationale="Synthetic wrong species",
        reviewed_by="synthetic-reviewer",
        evidence=[Evidence(gse="GSE2", field="title", quote="Synthetic mouse trap")],
    )
    absent = StudyGold(
        family_id="family-c",
        relevant=False,
        eligible=False,
        rationale="Synthetic verified absence",
        reviewed_by="synthetic-reviewer",
    )
    case = CaseGold(
        id="synthetic-01",
        split="development",
        prompt="Synthetic human bulk task",
        constraints={"max_datasets": 1},
        expected_action="proceed",
        required_workflow="load_only",
        studies={"GSE1": positive, "GSE2": trap, "GSE999": absent},
        reviewed_by="synthetic-reviewer",
        review_notes="Test only",
    )
    benchmark = Benchmark(
        id="synthetic-contract-test",
        version="1",
        data_kind="synthetic",
        frozen=True,
        snapshot_sha256=snapshot.digest(),
        cases=[case],
    )
    conditions = Conditions(
        model="fixture-model",
        source_access="fixture-snapshot",
        execution_access="python",
        time_budget_seconds=60,
        token_budget=100,
        snapshot_sha256=snapshot.digest(),
        prompt_sha256=prompt_digest(case),
        code_revision="fixture",
    )
    record = RunRecord(
        case_id=case.id,
        system="specialist",
        conditions=conditions,
        run_status="complete",
        action="proceed",
        ranking=["GSE1", "GSE2"],
        recommendations=["GSE1"],
        elapsed_seconds=1,
        input_tokens=10,
        output_tokens=10,
        raw_output_sha256="0" * 64,
        samples=[
            SamplePrediction(
                gse="GSE1", gsm="GSM1", fields={"group": "case"}, evidence={"group": evidence}
            )
        ],
        bundles=[
            BundleObservation(
                gse="GSE1",
                sample_ids=["GSM1"],
                units="counts",
                de_ready=False,
                integrity_passed=True,
            )
        ],
    )
    return benchmark, snapshot, case, record


def test_perfect_known_case_and_synthetic_not_scientific(fixture):
    benchmark, snapshot, case, record = fixture
    benchmark.validate_sources(snapshot)
    scored = score_case(case, record, snapshot)
    assert scored["metrics"]["correct_bundle_completion"]["value"] == 1
    assert scored["metrics"]["group_f1"]["case"]["value"] == 1
    assert scored["metrics"]["group_f1"]["control"]["value"] is None
    assert not scored["critical_errors"]
    comparison = compare(
        benchmark, snapshot, [record, record.model_copy(update={"system": "baseline"})]
    )
    assert comparison["comparison_ready"] is False
    assert comparison["data_kind"] == "synthetic"
    assert not comparison["pairing_errors"]


def test_empty_answer_does_not_score_perfect_precision(fixture):
    _, snapshot, case, record = fixture
    empty = record.model_copy(
        update={"ranking": [], "recommendations": [], "bundles": [], "samples": []}
    )
    result = score_case(case, empty, snapshot)["metrics"]
    assert result["precision_at_3_slots"]["value"] == 0
    assert result["precision_returned_at_3"]["value"] is None
    assert result["recall_at_10_in_pool"]["value"] == 0
    assert result["correct_bundle_completion"]["value"] == 0
    assert result["field_accuracy"]["value"] is None  # No selected study; task still fails.
    assert result["promised_workflow_complete"] is False


def test_swapped_label_fails_even_when_bundle_loads(fixture):
    _, snapshot, case, record = fixture
    record.samples[0].fields["group"] = "control"
    result = score_case(case, record, snapshot)
    assert result["metrics"]["correct_bundle_completion"]["value"] == 0
    assert result["metrics"]["group_f1"]["case"]["value"] == 0
    assert any("Swapped" in error for error in result["critical_errors"])


def test_unverified_is_not_called_nonexistent(fixture):
    _, snapshot, case, record = fixture
    record.ranking += ["GSE555"]
    result = score_case(case, record, snapshot)
    assert result["unverified_accessions"] == ["GSE555"]
    assert result["nonexistent_accessions"] == []
    assert result["incomplete"]


def test_verified_nonexistent_and_duplicate_and_ineligible_detected(fixture):
    _, snapshot, case, record = fixture
    record.ranking = ["GSE999", "GSE2", "GSE2"]
    record.recommendations = ["GSE2"]
    result = score_case(case, record, snapshot)
    assert result["nonexistent_accessions"] == ["GSE999"]
    assert any("Duplicate" in issue for issue in result["critical_errors"])
    assert any("ineligible" in issue for issue in result["critical_errors"])


def test_missing_baseline_and_budget_mismatch_prevent_comparison(fixture):
    benchmark, snapshot, _, record = fixture
    result = compare(benchmark, snapshot, [record])
    assert "missing" in result["pairing_errors"][0]
    assert result["summaries"]["development/baseline"]["answerable_task_completion"]["value"] == 0
    baseline = record.model_copy(deep=True, update={"system": "baseline"})
    baseline.conditions.time_budget_seconds = 999
    result = compare(benchmark, snapshot, [record, baseline])
    assert any("time_budget" in error for error in result["pairing_errors"])
    assert not result["comparison_ready"]


def test_duplicate_attempts_rejected(fixture):
    benchmark, snapshot, _, record = fixture
    with pytest.raises(ValueError, match="Duplicate run"):
        compare(benchmark, snapshot, [record, record])


def test_leaking_family_or_accession_rejected(fixture):
    benchmark, _, case, _ = fixture
    leaked = case.model_copy(deep=True, update={"id": "heldout-01", "split": "held_out"})
    with pytest.raises(ValidationError, match="changes split"):
        Benchmark.model_validate(
            {**benchmark.model_dump(), "cases": [case.model_dump(), leaked.model_dump()]}
        )
    leaked.studies = {"GSE100": case.studies["GSE1"]}
    with pytest.raises(ValidationError, match="leaks across splits"):
        Benchmark.model_validate(
            {**benchmark.model_dump(), "cases": [case.model_dump(), leaked.model_dump()]}
        )


def test_bad_gold_quote_rejected(fixture):
    benchmark, snapshot, _, _ = fixture
    benchmark.cases[0].studies["GSE1"].samples["GSM1"].evidence[0].quote = "invented"
    with pytest.raises(ValueError, match="Invalid gold sample evidence"):
        benchmark.validate_sources(snapshot)


def test_freeze_separates_public_from_gold_and_refuses_overwrite(fixture, tmp_path):
    benchmark, snapshot, _, _ = fixture
    gold = tmp_path / "gold.json"
    sources = tmp_path / "snapshot.json"
    gold.write_text(benchmark.model_dump_json())
    sources.write_text(snapshot.model_dump_json())
    freeze(gold, sources, tmp_path / "release")
    public = json.loads((tmp_path / "release/public/tasks.json").read_text())[0]
    assert "expected_action" not in public
    assert "studies" not in public
    assert "split" not in public
    assert json.loads((tmp_path / "release/private/gold.json").read_text())["frozen"]
    with pytest.raises(ValueError, match="exists"):
        freeze(gold, sources, tmp_path / "release")


def test_generic_ask_needs_specificity_review(fixture):
    _, snapshot, case, record = fixture
    case.expected_action = "ask"
    case.clarification_targets = ["material_type"]
    record.conditions.prompt_sha256 = prompt_digest(case)
    record.action = "ask"
    record.questions = ["Can you clarify?"]
    result = score_case(case, record, snapshot)
    assert not result["metrics"]["action_correct"]
    record.question_reviewed_by = "synthetic-reviewer"
    record.clarification_targets = ["material_type"]
    assert score_case(case, record, snapshot)["metrics"]["action_correct"]


def test_missing_tokens_and_over_budget_not_ready(fixture):
    _, snapshot, case, record = fixture
    record.input_tokens = None
    record.elapsed_seconds = 100
    result = score_case(case, record, snapshot)
    assert any("Token usage" in issue for issue in result["incomplete"])
    assert any("time budget" in issue for issue in result["incomplete"])


def test_workflow_not_run_is_not_a_pass(fixture):
    _, snapshot, case, record = fixture
    case.required_workflow = "downstream"
    result = score_case(case, record, snapshot)
    assert result["metrics"]["executed_workflow_success"]["value"] is None
    assert not result["metrics"]["promised_workflow_complete"]
    with pytest.raises(ValidationError, match="requires"):
        BundleObservation(
            gse="GSE1",
            sample_ids=[],
            units="counts",
            de_ready=True,
            integrity_passed=True,
            workflow_executed=True,
            workflow_passed=True,
        )


def test_correct_collection_does_not_require_de(fixture):
    _, snapshot, case, record = fixture
    assert not record.bundles[0].de_ready
    assert score_case(case, record, snapshot)["metrics"]["promised_workflow_complete"]


def test_report_preserves_failures_and_denominators(fixture):
    benchmark, snapshot, _, record = fixture
    report = render_report(compare(benchmark, snapshot, [record]))
    assert "0/1" in report
    assert "missing specialist or baseline" in report
    assert "N/A (0)" in report


def test_source_hash_change_rejected(fixture):
    benchmark, snapshot, _, _ = fixture
    snapshot.records["GSE1"].fields["title"] = ["changed"]
    with pytest.raises(ValueError, match="hash"):
        benchmark.validate_sources(snapshot)


def test_maximum_is_not_a_required_number_of_datasets(fixture):
    _, snapshot, case, record = fixture
    case.constraints = {"max_datasets": 3}
    record.conditions.prompt_sha256 = prompt_digest(case)
    assert score_case(case, record, snapshot)["metrics"]["promised_workflow_complete"]
    case.constraints["min_datasets"] = 2
    record.conditions.prompt_sha256 = prompt_digest(case)
    assert not score_case(case, record, snapshot)["metrics"]["promised_workflow_complete"]


@pytest.mark.parametrize(
    "limits", [{"max_datasets": 0}, {"min_datasets": 4}, {"max_datasets": True}]
)
def test_invalid_dataset_limits_rejected(fixture, limits):
    _, _, case, _ = fixture
    with pytest.raises(ValidationError, match="Dataset limits"):
        CaseGold.model_validate({**case.model_dump(), "constraints": limits})


def test_clarification_case_does_not_pollute_retrieval_scores(fixture):
    _, snapshot, case, record = fixture
    case.expected_action = "ask"
    case.clarification_targets = ["material_type"]
    record.action = "ask"
    record.questions = ["Do you need patient tissue or cell lines?"]
    record.clarification_targets = ["material_type"]
    record.question_reviewed_by = "reviewer"
    record.ranking = record.recommendations = []
    record.bundles = []
    result = score_case(case, record, snapshot)
    assert result["metrics"]["action_correct"]
    assert result["metrics"]["precision_at_3_slots"]["value"] is None


def test_artifact_inspection_detects_changed_h5ad_and_escape(tmp_path):
    import anndata as ad
    import numpy as np
    import pandas as pd

    from evals.observations import inspect_bundle, safe_file

    folder = tmp_path / "GSE1"
    folder.mkdir()
    (folder / "study.json").write_text(
        json.dumps(
            {"gse": "GSE1", "units": "counts", "de_ready": False, "matrix_file": "counts.tsv"}
        )
    )
    (folder / "samples.csv").write_text("gsm,group,evidence\nGSM1,case,{}\n")
    (folder / "counts.tsv").write_text("gene_id\tGSM1\ngene1\t12\n")
    (folder / "genes.tsv").write_text("gene_id\ngene1\n")
    dataset = ad.AnnData(
        X=np.array([[12]]),
        obs=pd.DataFrame({"group": ["case"]}, index=["GSM1"]),
        var=pd.DataFrame(index=["gene1"]),
        uns={"expression_units": "counts"},
    )
    dataset.write_h5ad(folder / "dataset.h5ad")
    assert inspect_bundle(folder)[0].integrity_passed
    dataset.X = np.array([[13]])
    dataset.write_h5ad(folder / "dataset.h5ad")
    observed, _ = inspect_bundle(folder)
    assert not observed.integrity_passed
    assert any("values differ" in issue for issue in observed.integrity_errors)
    with pytest.raises(ValueError, match="escapes"):
        safe_file(folder, "../secret")


def test_review_import_preserves_unknown_and_rejects_unreviewed(fixture, tmp_path):
    import csv

    from evals.annotations import assemble_gold

    benchmark, snapshot, case, _ = fixture
    snapshot.records = {"GSE1": snapshot.records["GSE1"]}
    (tmp_path / "public").mkdir()
    (tmp_path / "private").mkdir()
    (tmp_path / "public/snapshot.json").write_text(snapshot.model_dump_json())
    settings = {
        "benchmark_id": benchmark.id,
        "version": "1",
        "case": case.model_dump(exclude={"split", "studies"}),
    }
    (tmp_path / "private/case.json").write_text(json.dumps(settings))
    study = {
        "gse": "GSE1",
        "relevant": "true",
        "eligible": "true",
        "split": "development",
        "family_id": "one",
        "units": "counts",
        "de_ready": "false",
        "rationale": "Synthetic",
        "evidence_field": "title",
        "evidence_quote": "Synthetic positive",
        "reviewed_by": "reviewer",
    }
    sample = {
        "gse": "GSE1",
        "gsm": "GSM1",
        "include": "true",
        "group": "UNKNOWN",
        "tissue": "",
        "treatment": "",
        "time_point": "",
        "material_type": "",
        "exclusion_reason": "",
        "evidence_field": "characteristics_ch1",
        "evidence_quote": "condition: treated",
        "reviewed_by": "reviewer",
    }

    def save(name, rows):
        with (tmp_path / "private" / name).open("w") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    save("studies.csv", [study])
    save("samples.csv", [sample])
    gold, _ = assemble_gold(tmp_path)
    assert gold.cases[0].studies["GSE1"].samples["GSM1"].fields == {"group": None}
    save("samples.csv", [sample, sample])
    with pytest.raises(ValueError, match="exactly once"):
        assemble_gold(tmp_path)
    sample["include"] = ""
    save("samples.csv", [sample])
    with pytest.raises(ValueError, match="unreviewed"):
        assemble_gold(tmp_path)


async def test_frozen_pool_never_searches_and_cannot_be_relabeled(tmp_path, monkeypatch, fixture):
    from cell_ledger.geo.cache import CachedClient
    from cell_ledger.pipeline import RunRequest, run_pipeline
    from evals.observations import capture_run

    async def forbidden(*args, **kwargs):
        raise AssertionError("Frozen runs must not search live sources")

    monkeypatch.setattr("cell_ledger.pipeline.search_geo", forbidden)
    _, snapshot, case, record = fixture
    output = tmp_path / "output"
    manifest = await run_pipeline(
        RunRequest(topic="human bulk pancreatic cancer"),
        output,
        CachedClient(tmp_path / "cache", offline=True),
        candidate_pool=[],
        snapshot_sha256=snapshot.digest(),
    )
    assert manifest["eval_protocol"] == "frozen_pool"
    observed = capture_run(output, case.id, "specialist", record.conditions)
    assert observed.action == "no_results"
    assert observed.input_tokens is None
    record.conditions.protocol = "live_search"
    with pytest.raises(ValueError, match="protocol"):
        capture_run(output, case.id, "specialist", record.conditions)
