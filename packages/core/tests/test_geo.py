from pathlib import Path

import httpx
import pytest

from cell_ledger.geo.cache import CachedClient
from cell_ledger.geo.models import GeoError, SeriesNotFound, parse_soft


def test_soft_preserves_verbatim_repeated_evidence():
    series = parse_soft(
        "^SERIES = GSE1\n!Series_sample_id = GSM2\n^SAMPLE = GSM2\n"
        "!Sample_characteristics_ch1 = treatment: IFNG\n"
        "!Sample_characteristics_ch1 = donor: 3\n",
        "GSE1",
        "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE1",
    )
    assert series.samples[0].values("characteristics_ch1") == ["treatment: IFNG", "donor: 3"]


def test_unresolved_series_is_not_an_empty_success():
    with pytest.raises(SeriesNotFound):
        parse_soft("No items found", "GSE999999", "https://www.ncbi.nlm.nih.gov/")


async def test_cache_offline_and_integrity(tmp_path: Path):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=b"real response")

    url = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
        client = CachedClient(tmp_path, client=transport)
        original = await client.get(url)
        client.offline = True
        assert await client.get(url) == original
        assert len(calls) == 1
        with pytest.raises(GeoError, match="Offline cache miss"):
            await client.get(url, {"acc": "GSE2"})
        next(tmp_path.glob("*.bin")).write_bytes(b"corrupt")
        with pytest.raises(GeoError, match="checksum"):
            await client.get(url)


async def test_download_cap_and_untrusted_host(tmp_path: Path):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"12345"))
    ) as transport:
        client = CachedClient(tmp_path, client=transport, max_bytes=4)
        with pytest.raises(GeoError, match="size limit"):
            await client.get("https://ftp.ncbi.nlm.nih.gov/example")
        with pytest.raises(GeoError, match="Only HTTPS"):
            await client.get("https://example.org/matrix")
    assert not list(tmp_path.glob("*.bin"))


@pytest.mark.parametrize(
    "declaration, expected",
    [
        (
            "Supplementary files format and content: csv file of CPM of reads for each gene",
            "normalized",
        ),
        ("Supplementary files format and content: raw read counts for each gene", "counts"),
        ("Counts generated and normalized by CPM", "unknown"),
        ("", "unknown"),
    ],
)
async def test_submitter_units_require_explicit_file_description(declaration, expected, tmp_path):
    from cell_ledger.geo.models import GeoSample, GeoSeries
    from cell_ledger.geo.retrieval import expression_sources

    class Listing(CachedClient):
        async def get(self, url, params=None, *, _redirects=0):
            return b"<html></html>", {}

    source = GeoSeries(
        gse="GSE1",
        source_url="https://example.org",
        fields={"supplementary_file": ["https://ftp.ncbi.nlm.nih.gov/GSE1_raw_counts.csv.gz"]},
        samples=[
            GeoSample(
                gsm="GSM1",
                fields={
                    "organism_ch1": ["Homo sapiens"],
                    "library_strategy": ["RNA-Seq"],
                    "data_processing": [declaration],
                },
            )
        ],
    )
    result = await expression_sources(Listing(tmp_path), source)
    assert result[0]["kind"] == expected
    if expected != "unknown":
        assert result[0]["units_evidence"] == declaration
