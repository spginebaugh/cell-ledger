"""Cross-dataset comparison on synthetic runs with planted structure.

Five independent datasets share the same planted up/down genes. One more has its arms
swapped, one is unrelated (gene ids permuted), and one is a duplicate of another under
a new GSE. The duplicate must be excluded (shared samples, an input problem); the
swapped one must be flagged and quarantined with a question, not silently dropped; the
unrelated one must be flagged and still pooled; and the planted genes must come out
robust with the right sign. Statistical pieces are checked against statsmodels and by
simulation.
"""

from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm
from statsmodels.stats.meta_analysis import combine_effects

from cell_ledger.analysis import PipelineParams, run_pipeline
from cell_ledger.compare import (
    CompareParams,
    ComparisonReport,
    QuerySet,
    QuerySetMember,
    compare_query_set,
    run_comparison,
)
from cell_ledger.compare.load import RunData, load_run
from cell_ledger.compare.meta import (
    EffectMatrices,
    benjamini_hochberg,
    gene_table,
    random_effects,
    synthesize,
)
from cell_ledger.report.models import MarkerExpectation
from cell_ledger.samplesheet import Contrast, Group, SampleSheet

QUICK = PipelineParams(run_enrichment=False, figures=False)
NO_EXTRAS = CompareParams(figures=False, pooled_enrichment=False)
GOOD = ("GSE11", "GSE12", "GSE13", "GSE14", "GSE15")


def _renamed(syn, gse_n: int, *, swap: bool = False, permute: bool = False):  # type: ignore[no-untyped-def]
    """Give a synthetic dataset its own GSE and GSM ids (so runs are independent)."""
    off = gse_n * 1000
    ren = {c: f"GSM{off + int(c[3:])}" for c in syn.counts.columns}
    counts = syn.counts.rename(columns=ren)
    if permute:
        rng = np.random.default_rng(gse_n)
        counts = counts.copy()
        counts.index = pd.Index(rng.permutation(counts.index.to_numpy()), name="GeneID")
    samples = [
        s.model_copy(update={"gsm": ren.get(s.gsm, f"GSM{off + int(s.gsm[3:])}")})
        for s in syn.sheet.samples
    ]
    sheet = SampleSheet(gse=f"GSE{gse_n}", assay=syn.sheet.assay, title="syn", samples=samples)
    case = [ren.get(g, f"GSM{off + int(g[3:])}") for g in syn.contrast.case_gsms]
    ctrl = [ren.get(g, f"GSM{off + int(g[3:])}") for g in syn.contrast.control_gsms]
    if swap:
        for s in samples:  # relabel so the (swapped) contrast still passes the contract
            if s.gsm in case:
                s.group = Group.CONTROL
            elif s.gsm in ctrl:
                s.group = Group.CASE
        case, ctrl = ctrl, case
    contrast = Contrast(
        **{
            **syn.contrast.model_dump(),
            "gse": f"GSE{gse_n}",
            "case_gsms": case,
            "control_gsms": ctrl,
        }
    )
    return type(syn)(counts, syn.annotation, sheet, contrast, syn.up, syn.down)


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory, synthetic_factory) -> dict[str, Path]:  # type: ignore[no-untyped-def]
    root = tmp_path_factory.mktemp("runs")
    out: dict[str, Path] = {}
    specs = {
        "GSE11": dict(seed=1),
        "GSE12": dict(seed=2),
        "GSE13": dict(seed=3),
        "GSE14": dict(seed=4),
        "GSE15": dict(seed=5),
        "GSE16": dict(seed=6, swap=True),
        "GSE17": dict(seed=7, permute=True),
        "GSE18": dict(seed=1, dup_of="GSE11"),  # same samples as GSE11 under a new GSE
    }
    for gse, spec in specs.items():
        n = int(gse[3:])
        base = synthetic_factory(seed=int(spec["seed"]))
        syn = _renamed(
            base,
            11 if "dup_of" in spec else n,
            swap=bool(spec.get("swap")),
            permute=bool(spec.get("permute")),
        )
        if "dup_of" in spec:  # new GSE, identical GSM ids
            syn = type(syn)(
                syn.counts,
                syn.annotation,
                syn.sheet.model_copy(update={"gse": gse}),
                syn.contrast.model_copy(update={"gse": gse}),
                syn.up,
                syn.down,
            )
        d = root / gse
        d.mkdir()
        counts, annot = d / "counts.tsv", d / "annot.tsv"
        syn.counts.to_csv(counts, sep="\t")
        syn.annotation.to_csv(annot, sep="\t")
        rep = run_pipeline(
            counts_path=counts,
            annotation_path=annot,
            sheet=syn.sheet,
            contrast=syn.contrast,
            out_dir=d / "case_vs_control",
            params=QUICK,
        )
        assert rep.status == "complete", (gse, rep.blockers)
        assert rep.fingerprint and rep.de and rep.de.summary.gsms_fitted
        out[gse] = d / "case_vs_control"
    return out


def _cmp(runs: dict[str, Path], out: Path, keys, **kw) -> ComparisonReport:  # type: ignore[no-untyped-def]
    params = kw.pop("params", NO_EXTRAS)
    return run_comparison(
        [runs[k] for k in keys],
        out,
        name="synthetic_set",
        question="planted case vs control",
        case_label="case",
        control_label="control",
        params=params,
        **kw,
    )


def test_flags_quarantine_and_synthesis(runs: dict[str, Path], tmp_path: Path) -> None:
    params = NO_EXTRAS.model_copy(
        update={
            "genes_of_interest": ["G10", "G60", "G500", "NOPE"],
            "markers": [
                MarkerExpectation(symbol="G11", direction="up"),
                MarkerExpectation(symbol="G61", direction="down"),
            ],
            "figures": True,
            # the synthetic signal is 100 of 1500 genes, so the reversal is milder than a
            # real swapped dataset; the thresholds are parameters, the mechanism is the test
            "reversed_concordance": -0.15,
            "low_concordance": 0.15,
        }
    )
    report = _cmp(
        runs,
        tmp_path / "cmp",
        list(runs),
        params=params,
        strata={"GSE11": "a", "GSE12": "a", "GSE13": "a", "GSE14": "b", "GSE15": "b"},
    )
    assert report.status == "complete", report.error
    # the duplicate is an input problem and is excluded; disagreement never excludes
    assert [(e.gse, e.reason) for e in report.excluded] == [("GSE18", "shares_samples")]
    by = {m.gse: m for m in report.members}
    assert set(by) == set(GOOD) | {"GSE16", "GSE17"}
    assert by["GSE16"].flags == ["labels_reversed"] and by["GSE16"].pooled is False
    assert by["GSE17"].flags == ["low_concordance"] and by["GSE17"].pooled is True
    assert all(by[g].flags == [] and by[g].pooled for g in ("GSE11", "GSE12", "GSE13"))
    # stratum b has two runs: nothing to judge them against, still pooled
    assert all(
        by[g].flags == ["concordance_unassessed"] and by[g].pooled for g in ("GSE14", "GSE15")
    )
    assert all(m.unshrunk_se_source == "stored" for m in report.members)
    assert len(report.questions) == 1 and "GSE16" in report.questions[0]
    assert (tmp_path / "cmp" / "questions.md").exists()
    # strata are judged within themselves; unassigned runs against every run
    assert by["GSE11"].concordance_group == "a" and by["GSE16"].concordance_group == "all"
    conc = report.concordance
    assert conc is not None
    good_means = [conc.mean_to_others[by[g].label] for g in ("GSE11", "GSE12", "GSE13")]
    assert all(v is not None and v > 0.1 for v in good_means), conc.mean_to_others
    swapped = conc.mean_to_others[by["GSE16"].label]
    assert swapped is not None and swapped < -0.15

    g = report.genes
    assert g is not None and set(g.members) == {by[x].label for x in (*GOOD, "GSE17")}
    assert g.alpha == 0.05 and g.interval == "hksj"
    # the unrelated run is pooled (flagged, not excluded): its noise inflates tau2 and the
    # HKSJ test loses power, which the sensitivity row below makes visible
    assert g.n_robust_up >= 5 and g.n_robust_down >= 5
    planted_up = {str(i) for i in range(10, 60)} | {"3"}  # "3" is XIST: cases are female
    planted_down = {str(i) for i in range(60, 110)} | {"2"}  # "2" is RPS4Y1: controls are male
    assert {x.gene_id for x in g.top_up} <= planted_up
    assert {x.gene_id for x in g.top_down} <= planted_down
    # the permuted run contributes an unrelated gene's effect (or none): the five good
    # runs are always present and always agree
    assert all(x.n_tested >= 5 and x.n_agree_pooled >= 5 for x in g.top_up[:10])
    # Top rows carry each dataset's own estimate so the browser can draw them side by side.
    assert all(set(x.effects) == set(g.members) for x in (*g.top_up, *g.top_down))
    for x in g.top_up[:5]:
        for lab in g.members:
            e = x.effects[lab]
            if e.padj is not None and e.padj < g.alpha:
                assert e.log2fc is not None and e.log2fc > 0
    # three runs: HKSJ with two degrees of freedom is conservative, by design
    assert set(report.strata) == {"a", "b"} and report.strata["a"].n_robust_up >= 5
    assert len(report.strata["b"].members) == 2  # k=2: HKSJ with one df, few robust genes

    # with the off-topic run pooled, verdicts are weaker; the clean-pool test below checks
    # the verdict logic itself
    look = {r.query: r for r in report.gene_lookup}
    assert set(look) == {"G10", "G60", "G500", "NOPE"}
    assert look["NOPE"].verdict == "not_found" and look["G500"].verdict == "no_evidence"
    assert look["G10"].per_member[by["GSE17"].label] in {"no_evidence", "not_tested", "untestable"}
    assert len(look["G10"].leave_one_out) == 6
    assert report.markers is not None and len(report.leave_one_out) == 6

    # sensitivity: the quarantined run added back, the low-concordance run taken out
    sens = {(s.member.split(":")[0], s.flag): s for s in report.sensitivity}
    assert set(sens) == {("GSE16", "labels_reversed"), ("GSE17", "low_concordance")}
    rev = sens[("GSE16", "labels_reversed")]
    assert rev.pooled_by_default is False
    assert rev.n_robust_alternative < rev.n_robust_default
    low = sens[("GSE17", "low_concordance")]
    assert low.pooled_by_default is True
    assert low.n_robust_alternative > 2 * low.n_robust_default  # without it, power returns

    for f in (
        "comparison.json",
        "comparison.md",
        "questions.md",
        "gene_table.tsv",
        "members.tsv",
        "excluded.tsv",
        "concordance.tsv",
        "strata/a.tsv",
        "strata/b.tsv",
    ):
        assert (tmp_path / "cmp" / f).exists(), f
    assert (tmp_path / "cmp" / report.figures["concordance"]).exists()
    assert (tmp_path / "cmp" / report.figures["forest"]).exists()
    loaded = ComparisonReport.model_validate_json(
        (tmp_path / "cmp" / "comparison.json").read_text()
    )
    assert loaded.genes is not None and loaded.genes.n_robust == g.n_robust
    wide = pd.read_csv(tmp_path / "cmp" / "gene_table.tsv", sep="\t", index_col=0)
    assert f"lfc__{by['GSE11'].label}" in wide.columns
    assert int(cast(Any, wide["robust"]).sum()) >= 10
    md = (tmp_path / "cmp" / "comparison.md").read_text()
    assert "labels_reversed" in md and "Questions for the user" in md and "Sensitivity" in md


def test_pool_flagged_overrides_quarantine(runs: dict[str, Path], tmp_path: Path) -> None:
    report = _cmp(
        runs,
        tmp_path / "pf",
        (*GOOD, "GSE16"),
        params=NO_EXTRAS.model_copy(update={"pool_flagged": True}),
    )
    by = {m.gse: m for m in report.members}
    assert by["GSE16"].flags == ["labels_reversed"] and by["GSE16"].pooled is True
    assert report.questions and "pooled anyway" in report.questions[0]


def test_two_runs_cannot_be_judged_and_use_effective_minimum(
    runs: dict[str, Path], tmp_path: Path
) -> None:
    params = NO_EXTRAS.model_copy(update={"genes_of_interest": ["G10"]})
    report = _cmp(runs, tmp_path / "two", ("GSE11", "GSE16"), params=params)
    assert report.status == "complete" and len(report.members) == 2 and not report.excluded
    assert all("concordance_unassessed" in m.flags and m.pooled for m in report.members)
    assert report.effective_min_studies == 2
    assert any("same minimum applies to gene lookups" in w for w in report.warnings)
    assert report.genes is not None and report.genes.min_studies == 2
    # the lookup uses the same effective minimum as the table: no spurious "insufficient"
    assert report.gene_lookup[0].verdict != "insufficient"
    assert report.leave_one_out == [] and report.gene_lookup[0].leave_one_out == []


def test_single_usable_run_is_insufficient(runs: dict[str, Path], tmp_path: Path) -> None:
    report = _cmp(runs, tmp_path / "one", ("GSE11", "GSE18"))
    assert report.status == "insufficient" and report.genes is None
    assert [e.reason for e in report.excluded] == ["shares_samples"]
    assert (tmp_path / "one" / "comparison.json").exists()


def test_missing_and_unreadable_members_are_recorded(runs: dict[str, Path], tmp_path: Path) -> None:
    broken = tmp_path / "broken" / "GSE99" / "case_vs_control"
    broken.mkdir(parents=True)
    (broken / "report.json").write_text("{not json")
    report = run_comparison(
        [runs["GSE11"], runs["GSE12"], runs["GSE13"], tmp_path / "nowhere", broken],
        tmp_path / "miss",
        name="miss",
        question="q",
        case_label="a",
        control_label="b",
        params=NO_EXTRAS,
    )
    assert report.status == "complete" and len(report.members) == 3
    assert sorted(e.reason for e in report.excluded) == ["missing", "unreadable"]


def test_query_set_records_missing_member_instead_of_raising(
    runs: dict[str, Path], tmp_path: Path
) -> None:
    root = runs["GSE11"].parent.parent
    qs = QuerySet(
        name="syn",
        question="q",
        case_label="case",
        control_label="control",
        members=[
            QuerySetMember(gse=g, contrast="case_vs_control", stratum="s")
            for g in ("GSE11", "GSE12", "GSE13", "GSE14")
        ]
        + [QuerySetMember(gse="GSE99", contrast="case_vs_control")],
        markers=[MarkerExpectation(symbol="G10", direction="up")],
    )
    report = compare_query_set(qs, root, tmp_path / "qs", params=NO_EXTRAS)
    assert report.status == "complete", report.error
    assert report.markers and report.markers.n_recovered == 1, report.markers
    assert [e.reason for e in report.excluded] == ["missing"]
    assert report.strata == {}  # one stratum only: nothing to split


def test_stratum_names_cannot_escape_the_output_directory(
    runs: dict[str, Path], tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="slug"):
        _cmp(runs, tmp_path / "esc", GOOD, strata={"GSE11": "../../escaped", "GSE12": "ok"})
    with pytest.raises(Exception):  # noqa: B017 (pydantic validation error)
        QuerySetMember(gse="GSE1", contrast="c", stratum="../x")
    assert not (tmp_path / "escaped.tsv").exists()


def test_refuses_foreign_directory(tmp_path: Path) -> None:
    out = tmp_path / "mine"
    out.mkdir()
    (out / "notes.txt").write_text("precious")
    with pytest.raises(ValueError, match="refusing"):
        run_comparison([], out, name="x", question="q", case_label="a", control_label="b")


def test_legacy_run_reconstructs_the_unshrunk_se(runs: dict[str, Path], tmp_path: Path) -> None:
    legacy = tmp_path / "legacy" / "GSE11" / "case_vs_control"
    legacy.parent.mkdir(parents=True)
    shutil.copytree(runs["GSE11"], legacy)
    de = pd.read_csv(legacy / "de_results.tsv", sep="\t", index_col=0)
    de.drop(columns=["lfc_se_unshrunk"]).to_csv(legacy / "de_results.tsv", sep="\t")
    stored = load_run(runs["GSE11"]).effect_table()
    rebuilt = load_run(legacy).effect_table()
    assert stored is not None and rebuilt is not None
    common = stored.index.intersection(rebuilt.index)
    np.testing.assert_allclose(
        stored.loc[common, "se"].to_numpy(), rebuilt.loc[common, "se"].to_numpy(), rtol=1e-6
    )
    report = run_comparison(
        [legacy, runs["GSE12"], runs["GSE13"]],
        tmp_path / "leg",
        name="leg",
        question="q",
        case_label="case",
        control_label="control",
        params=NO_EXTRAS,
    )
    member = next(m for m in report.members if m.run_dir == str(legacy))
    assert member.unshrunk_se_source == "reconstructed"
    assert any("reconstructed" in w for w in report.warnings)
    json.loads((tmp_path / "leg" / "comparison.json").read_text())


# --------------------------------------------------------------------------- statistics


def _matrices(lfc: dict[str, list[float]], se: dict[str, list[float]], padj=None):  # type: ignore[no-untyped-def]
    """Build an EffectMatrices by hand (no runs) for unit tests of the synthesis."""
    genes = [f"g{i}" for i in range(len(next(iter(lfc.values()))))]
    m = object.__new__(EffectMatrices)
    m.labels = list(lfc)
    idx = pd.Index(genes, name="gene_id")
    m.lfc = pd.DataFrame(lfc, index=idx, dtype=float)
    m.se = pd.DataFrame(se, index=idx, dtype=float)
    m.stat = m.lfc / m.se
    if padj is None:
        m.padj = pd.DataFrame(
            2 * norm.sf(np.abs(m.stat.to_numpy())), index=idx, columns=m.labels, dtype=float
        )
    else:
        m.padj = pd.DataFrame(padj, index=idx, dtype=float)
    m.symbol = pd.Series(genes, index=idx, dtype=str).str.upper()
    m.n_samples = pd.Series(8.0, index=m.labels)
    return m


def test_random_effects_matches_statsmodels() -> None:
    rng = np.random.default_rng(0)
    y = rng.normal(0.8, 0.5, size=(40, 5))
    s = rng.uniform(0.1, 0.6, size=(40, 5))
    lfc = pd.DataFrame(y, columns=list("abcde"))
    se = pd.DataFrame(s, columns=list("abcde"))
    out = random_effects(lfc, se, min_studies=3, interval="hksj")
    for i in range(0, 40, 7):
        ref = cast(Any, combine_effects(y[i], s[i] ** 2, method_re="dl"))
        if ref.tau2 < 0:  # statsmodels keeps a negative DL tau2; DerSimonian-Laird truncates
            assert out.loc[i, "tau2"] == 0.0
            continue
        assert out.loc[i, "tau2"] == pytest.approx(ref.tau2, rel=1e-9, abs=1e-12)
        assert out.loc[i, "pooled_log2fc"] == pytest.approx(ref.mean_effect_re, rel=1e-9)
        assert out.loc[i, "pooled_se"] == pytest.approx(ref.sd_eff_w_re, rel=1e-9)
        assert out.loc[i, "se_ci"] == pytest.approx(ref.sd_eff_w_re_hksj, rel=1e-9)
        lo, hi = ref.conf_int(use_t=True)[3]
        assert out.loc[i, "ci_low"] == pytest.approx(lo, rel=1e-6)
        assert out.loc[i, "ci_high"] == pytest.approx(hi, rel=1e-6)
    normal = random_effects(lfc, se, min_studies=3, interval="normal")
    assert np.allclose(normal["se_ci"], normal["pooled_se"])


def test_null_effects_are_calibrated_by_simulation() -> None:
    """Under the null with 5 heterogeneous studies, HKSJ rejects at about alpha while the
    normal approximation rejects too often; with a real effect, both detect it."""
    rng = np.random.default_rng(1)
    n_genes, k, tau = 4000, 5, 0.3
    se = rng.uniform(0.15, 0.5, size=(n_genes, k))
    y_null = rng.normal(0, 1, size=(n_genes, k)) * np.sqrt(se**2 + tau**2)
    lfc, sef = pd.DataFrame(y_null), pd.DataFrame(se)
    hksj = random_effects(lfc, sef, min_studies=3, interval="hksj")
    normal = random_effects(lfc, sef, min_studies=3, interval="normal")
    fp_hksj = float(cast(Any, hksj["pvalue"] < 0.05).mean())
    fp_normal = float(cast(Any, normal["pvalue"] < 0.05).mean())
    assert 0.03 <= fp_hksj <= 0.07, fp_hksj
    assert fp_normal > fp_hksj
    alt = random_effects(pd.DataFrame(1.0 + y_null), sef, 3)
    power = float(cast(Any, alt["pvalue"] < 0.05).mean())
    assert power > 0.9
    # missing genes: a gene seen in two studies is not pooled at min_studies=3
    lfc.iloc[0, 2:] = np.nan
    again = random_effects(lfc, sef, 3)
    assert np.isnan(again.loc[0, "pooled_log2fc"]) and again.loc[0, "k"] == 2


def test_agreement_is_measured_against_the_pooled_direction() -> None:
    # two weak positive studies, one precise negative: pooled is negative
    m = _matrices(
        {"a": [0.3, 1.0], "b": [0.2, 1.0], "c": [-1.5, 1.0]},
        {"a": [0.6, 0.1], "b": [0.6, 0.1], "c": [0.1, 0.1]},
    )
    t = gene_table(m, CompareParams(), min_studies=3)
    row = t.loc["g0"]
    assert row["pooled_log2fc"] < 0
    assert row["n_pos"] == 2 and row["n_neg"] == 1
    assert row["n_agree_pooled"] == 1 and row["sign_consistency"] == pytest.approx(1 / 3)
    assert bool(row["majority_disagrees_pooled"]) is True and not row["robust"]
    assert t.loc["g1", "n_agree_pooled"] == 3 and t.loc["g1", "robust"]


def test_tested_counts_pooling_contributors_not_padj() -> None:
    m = _matrices(
        {"a": [1.0], "b": [1.1], "c": [0.9]},
        {"a": [0.2], "b": [0.2], "c": [0.2]},
        padj={"a": [0.001], "b": [0.001], "c": [np.nan]},  # c: independently filtered
    )
    t = gene_table(m, CompareParams(), min_studies=3)
    row = t.loc["g0"]
    assert row["n_tested"] == 3 and row["k"] == 3 and row["n_with_padj"] == 2
    assert row["n_sig"] == 2 and row["replication"] == pytest.approx(2 / 3)
    assert not np.isnan(row["pooled_log2fc"])


def test_alpha_and_thresholds_flow_from_params() -> None:
    m = _matrices(
        {"a": [0.5, 0.5], "b": [0.5, 0.5], "c": [0.5, 0.5]},
        {"a": [0.25, 0.25], "b": [0.25, 0.25], "c": [0.25, 0.25]},
        padj={"a": [0.08, 0.5], "b": [0.08, 0.5], "c": [0.08, 0.5]},
    )
    loose = CompareParams(alpha=0.1, min_replication=0.6, sign_consistency=0.9)
    t = gene_table(m, loose, min_studies=3)
    s = synthesize(t, m.labels, loose, min_studies=3)
    assert s.alpha == 0.1 and s.min_replication == 0.6 and s.sign_consistency == 0.9
    assert s.n_sig_pooled == int(cast(Any, t["padj"] < 0.1).sum())
    assert s.n_robust == int(cast(Any, t["robust"]).sum())
    strict = gene_table(m, CompareParams(alpha=0.01), min_studies=3)
    assert strict.loc["g0", "n_sig"] == 0 and not strict.loc["g0", "robust"]


def test_benjamini_hochberg() -> None:
    p = np.array([0.01, 0.04, 0.03, np.nan, 0.5])
    adj = benjamini_hochberg(p)
    assert np.isnan(adj[3])
    assert adj[0] == pytest.approx(0.04) and adj[4] == pytest.approx(0.5)
    assert adj[1] == pytest.approx(0.04 * 4 / 3) and adj[2] == pytest.approx(0.04 * 4 / 3)


def test_run_data_uses_fitted_membership(runs: dict[str, Path]) -> None:
    r: RunData = load_run(runs["GSE11"])
    assert r.report.de is not None
    assert r.gsms_fitted == set(r.report.de.summary.gsms_fitted)
    assert r.n_fitted == 8  # 4 vs 4 fitted (GSM42 has no counts)


def test_lookups_markers_and_leave_one_out_on_a_clean_pool(
    runs: dict[str, Path], tmp_path: Path
) -> None:
    """Five concordant runs plus the swapped one (quarantined): the verdict logic."""
    params = NO_EXTRAS.model_copy(
        update={
            "genes_of_interest": ["G10", "G60", "G500", "NOPE"],
            "markers": [
                MarkerExpectation(symbol="G11", direction="up"),
                MarkerExpectation(symbol="G61", direction="down"),
            ],
            "reversed_concordance": -0.15,
        }
    )
    report = _cmp(runs, tmp_path / "clean", (*GOOD, "GSE16"), params=params)
    assert report.status == "complete", report.error
    by = {m.gse: m for m in report.members}
    assert by["GSE16"].pooled is False and report.genes is not None
    assert len(report.genes.members) == 5
    assert report.genes.n_robust_up >= 40 and report.genes.n_robust_down >= 40
    look = {r.query: r for r in report.gene_lookup}
    assert look["G10"].verdict == "replicated_up" and look["G60"].verdict == "replicated_down"
    assert look["G500"].verdict == "no_evidence" and look["NOPE"].verdict == "not_found"
    assert set(look["G10"].per_member.values()) == {"up"}
    assert len(look["G10"].leave_one_out) == 5 and look["G10"].driven_by == []
    assert all(x.verdict == "replicated_up" for x in look["G10"].leave_one_out)
    assert report.markers is not None and report.markers.n_recovered == 2
    assert len(report.leave_one_out) == 5
    assert all(x.robust_retained > 0.8 for x in report.leave_one_out)
    assert all(
        x.spearman_pooled_z is not None and x.spearman_pooled_z > 0.8 for x in report.leave_one_out
    )


def test_pooled_genes_file_is_quantised_and_covers_every_member(
    runs: dict[str, Path], tmp_path: Path
) -> None:
    """The browser file: pooled genes only, every included dataset (set-aside ones last),
    fold changes to 0.01, -log10 padj to 0.1, and the per-dataset flags the wall draws."""
    params = NO_EXTRAS.model_copy(update={"reversed_concordance": -0.15})
    out = tmp_path / "pooled"
    report = _cmp(runs, out, (*GOOD, "GSE16"), params=params)
    assert report.status == "complete", report.error
    assert report.files["pooled_genes"] == "pooled_genes.json.gz"
    with gzip.open(out / "pooled_genes.json.gz", "rt") as f:
        doc = json.load(f)
    table = pd.read_csv(out / "gene_table.tsv", sep="\t", index_col=0)
    pooled = table.loc[table["pooled_log2fc"].notna()]
    assert doc["n"] == len(pooled) == len(doc["gene_id"]) == len(doc["log2fc"])
    labels = [m["label"] for m in doc["members"]]
    assert len(labels) == 6 and labels[-1].startswith("GSE16:")
    assert [m["pooled"] for m in doc["members"]] == [True] * 5 + [False]
    assert doc["members"][-1]["flags"] == ["labels_reversed"]
    assert all(m["n_samples"] > 0 for m in doc["members"])
    for key in ("member_lfc", "member_se", "member_sig"):
        assert len(doc[key]) == 6 and all(len(col) == doc["n"] for col in doc[key])
    # quantisation: integers at the declared scales, recoverable to within half a unit
    i = doc["gene_id"].index("10")
    row = pooled.loc[10]
    assert doc["symbol"][i] == "G10" and doc["robust"][i] == 1
    assert abs(doc["log2fc"][i] / doc["lfc_scale"] - row["pooled_log2fc"]) <= 0.005
    assert abs(doc["nlp"][i] / doc["nlp_scale"] + np.log10(row["padj"])) <= 0.05
    assert doc["n_tested"][i] == row["n_tested"] == 5 and doc["n_sig"][i] == 5
    j = labels.index(f"GSE11:{report.members[0].contrast}")
    assert abs(doc["member_lfc"][j][i] / 100 - row[f"lfc__{labels[j]}"]) <= 0.005
    assert doc["member_sig"][j][i] == int(row[f"padj__{labels[j]}"] < params.alpha)
    # the swapped dataset points the other way for the planted gene
    assert doc["member_lfc"][-1][i] is not None and doc["member_lfc"][-1][i] < 0
    assert all(isinstance(v, int) for col in doc["member_lfc"] for v in col if v is not None)
