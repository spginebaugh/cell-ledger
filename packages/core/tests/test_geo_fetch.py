"""fetch_series against a fake GEO FTP host: layout, checks and exclusions."""

import gzip
import json
from pathlib import Path

import httpx

from cell_ledger.geo import DatasetExclusion, SampleExclusion, ensure_annotation, fetch_series
from cell_ledger.geo.fetch import ANNOTATION_URL, counts_url, series_stem, soft_url

SOFT = """\
^SERIES = GSE100001
!Series_title = Drug X in PANC-1 cells
!Series_summary = Treated vs vehicle.
!Series_overall_design = 2 vs 2, plus one mouse xenograft
!Series_pubmed_id = 42
^SAMPLE = GSM1
!Sample_title = vehicle 1
!Sample_source_name_ch1 = PANC-1
!Sample_organism_ch1 = Homo sapiens
!Sample_characteristics_ch1 = treatment: vehicle
!Sample_library_strategy = RNA-Seq
^SAMPLE = GSM2
!Sample_title = drug 1
!Sample_source_name_ch1 = PANC-1
!Sample_organism_ch1 = Homo sapiens
!Sample_characteristics_ch1 = treatment: drug X
!Sample_library_strategy = RNA-Seq
^SAMPLE = GSM3
!Sample_title = xenograft
!Sample_organism_ch1 = Mus musculus
!Sample_library_strategy = RNA-Seq
^SAMPLE = GSM4
!Sample_title = drug 2, not quantified by NCBI
!Sample_organism_ch1 = Homo sapiens
!Sample_library_strategy = RNA-Seq
"""
COUNTS = "GeneID\tGSM1\tGSM2\tGSM3\n1\t10\t0\t5\n2\t300\t250\t7\n"


def _gz(text: str) -> bytes:
    return gzip.compress(text.encode())


def _transport(files: dict[str, bytes], seen: list[str]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(f"{request.method} {url}")
        if url in files:
            return httpx.Response(200, content=b"" if request.method == "HEAD" else files[url])
        return httpx.Response(404)

    return httpx.MockTransport(handle)


async def _fetch(files: dict[str, bytes], gse: str, root: Path, seen: list[str] | None = None):
    async with httpx.AsyncClient(
        transport=_transport(files, seen if seen is not None else [])
    ) as h:
        return await fetch_series(h, gse, root)


def _series(gse: str = "GSE100001", counts: str = COUNTS) -> dict[str, bytes]:
    return {counts_url(gse): _gz(counts), soft_url(gse): _gz(SOFT)}


def test_series_stem() -> None:
    assert series_stem("GSE164073") == "GSE164nnn"
    assert series_stem("GSE1") == "GSEnnn"


async def test_ready_series_layout_and_sample_exclusions(tmp_path: Path) -> None:
    record = await _fetch(_series(), "GSE100001", tmp_path)

    out = tmp_path / "GSE100001"
    counts = out / "GSE100001_raw_counts_GRCh38.p13_NCBI.tsv.gz"
    assert gzip.decompress(counts.read_bytes()).decode() == COUNTS  # untouched
    assert (out / "GSE100001_family.soft.gz").exists()
    assert json.loads((out / "dataset.json").read_text())["gse"] == "GSE100001"

    assert record.status == "ready" and record.exclusions == []
    assert record.title == "Drug X in PANC-1 cells" and record.pubmed_ids == ["42"]
    by_gsm = {s.gsm: s for s in record.samples}
    assert by_gsm["GSM1"].eligible and by_gsm["GSM2"].eligible
    assert by_gsm["GSM2"].characteristics == ["treatment: drug X"]
    assert by_gsm["GSM3"].exclusions == [SampleExclusion.NOT_HUMAN]
    assert by_gsm["GSM4"].exclusions == [SampleExclusion.NOT_IN_COUNTS]
    assert record.n_eligible == 2

    assert record.counts_check is not None
    assert (record.counts_check.n_genes, record.counts_check.n_columns) == (2, 3)
    assert record.counts_check.all_nonneg_integers
    assert record.files["counts"].md5 and record.files["counts"].url == counts_url("GSE100001")


async def test_series_without_ncbi_counts_is_excluded_without_downloading(tmp_path: Path) -> None:
    seen: list[str] = []
    record = await _fetch({}, "GSE100002", tmp_path, seen)

    assert record.status == "excluded"
    assert record.exclusions == [DatasetExclusion.NO_NCBI_COUNTS]
    assert not any(s.startswith("GET") and "soft" in s for s in seen)


async def test_counts_filename_discovered_from_listing(tmp_path: Path) -> None:
    gse, name = "GSE100003", "GSE100003_raw_counts_GRCh38.p14_NCBI.tsv.gz"
    folder = "https://ftp.ncbi.nlm.nih.gov/geo/rnaseq_counts/GSE100nnn/"
    files = {
        folder: f'<a href="{name}">{name}</a>'.encode(),
        counts_url(gse, name): _gz(COUNTS),
        soft_url(gse): _gz(SOFT),
    }
    record = await _fetch(files, gse, tmp_path)
    assert record.status == "ready" and record.files["counts"].name == name


async def test_non_integer_counts_exclude_dataset(tmp_path: Path) -> None:
    record = await _fetch(_series(counts="GeneID\tGSM1\n1\t3.5\n"), "GSE100001", tmp_path)
    assert DatasetExclusion.COUNTS_NOT_INTEGER in record.exclusions
    assert record.status == "excluded"


async def test_second_fetch_reuses_files(tmp_path: Path) -> None:
    await _fetch(_series(), "GSE100001", tmp_path)
    seen: list[str] = []
    await _fetch(_series(), "GSE100001", tmp_path, seen)
    assert [s for s in seen if s.startswith("GET")] == []


async def test_annotation_downloaded_once(tmp_path: Path) -> None:
    seen: list[str] = []
    files = {ANNOTATION_URL: _gz("GeneID\tSymbol\n1\tA1BG\n")}
    async with httpx.AsyncClient(transport=_transport(files, seen)) as h:
        first = await ensure_annotation(h, tmp_path)
        second = await ensure_annotation(h, tmp_path)
    assert first.md5 == second.md5
    assert len(seen) == 1
