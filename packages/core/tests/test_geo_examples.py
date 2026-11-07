"""The ten curated example datasets: sheet + contrast fixtures must validate and be DE-ready.

The counts matrices themselves are gitignored under ``data/geo``; the last test
reconciles them against the sheets only when they are present locally.
"""

import gzip
import json
from pathlib import Path

import pytest

from cell_ledger.samplesheet import Contrast, Group, SampleSheet

FIXTURES = Path(__file__).parent / "fixtures" / "geo_examples"
DATA = Path(__file__).parents[3] / "data" / "geo"
EXAMPLES = sorted(FIXTURES.glob("GSE*.json"))


def _load(path: Path) -> tuple[SampleSheet, list[Contrast]]:
    doc = json.loads(path.read_text())
    return SampleSheet.model_validate(doc["samplesheet"]), [
        Contrast.model_validate(c) for c in doc["contrasts"]
    ]


TEN = {
    "GSE114286", "GSE67785", "GSE185492", "GSE79544", "GSE135631",
    "GSE140343", "GSE232753", "GSE233547", "GSE111414", "GSE82227",
}  # fmt: skip
SETS = sorted((FIXTURES.parent / "query_sets").glob("*.json"))


def test_ten_examples_present() -> None:
    assert {p.stem for p in EXAMPLES} >= TEN


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_query_set_members_have_designs(path: Path) -> None:
    from cell_ledger.compare import QuerySet

    qs = QuerySet.model_validate_json(path.read_text())
    assert qs.name == path.stem and len(qs.members) >= 3
    designs = {p.stem for p in EXAMPLES}
    for m in qs.members:
        assert m.gse in designs, m.gse
        _, contrasts = _load(FIXTURES / f"{m.gse}.json")
        assert m.contrast in {c.name for c in contrasts}, (m.gse, m.contrast)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_example_is_de_ready(path: Path) -> None:
    sheet, contrasts = _load(path)
    assert sheet.gse == path.stem
    assert contrasts, "every example has at least one contrast"
    for c in contrasts:
        assert c.problems(sheet) == []
        assert len(c.case_gsms) >= 3 and len(c.control_gsms) >= 3
    labelled = [s for s in sheet.samples if s.group in (Group.CASE, Group.CONTROL)]
    assert labelled, "every example labels some samples"
    assert all(s.evidence for s in labelled), "every case/control label cites evidence"
    assert all(s.raw for s in sheet.samples), "raw characteristics kept for every sample"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_contrast_arms_have_counts(path: Path) -> None:
    """Counts columns are GSMs; both arms of every contrast keep >= 3 quantified samples.

    Sheets may deliberately leave out GSMs (other assays, other diseases, treated
    arms), so counts columns outside the sheet are allowed and are ignored downstream.
    """
    counts = DATA / path.stem / f"{path.stem}_raw_counts_GRCh38.p13_NCBI.tsv.gz"
    if not counts.exists():
        pytest.skip("local GEO data not downloaded (scripts/fetch_geo_examples.py)")
    sheet, contrasts = _load(path)
    with gzip.open(counts, "rt") as f:
        header = f.readline().rstrip("\n").split("\t")
    assert header[0] == "GeneID"
    cols = set(header[1:])
    assert all(c.startswith("GSM") for c in cols)
    assert cols & set(sheet.gsms)
    for c in contrasts:
        assert len(cols & set(c.case_gsms)) >= 3 and len(cols & set(c.control_gsms)) >= 3
