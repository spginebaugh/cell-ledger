"""GeoClient's file-server reads: a series' SOFT record and its count table's header."""

import gzip

import httpx
import pytest

from cell_ledger.geo import GeoClient
from cell_ledger.geo.fetch import FTP, counts_url, soft_url

SOFT = "^SERIES = GSE1\n!Series_title = T\n^SAMPLE = GSM1\n!Sample_title = a\n"


def _client(files: dict[str, bytes], seen: list[str]) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if url in files:
            return httpx.Response(200, content=files[url])
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


async def test_series_record_parses_the_family_soft() -> None:
    async with _client({soft_url("GSE1"): gzip.compress(SOFT.encode())}, []) as http:
        rec = await GeoClient(http).series_record("GSE1")
    assert rec.gse == "GSE1" and [s.title for s in rec.samples] == ["a"]


async def test_count_columns_reads_only_the_header_line() -> None:
    body = "GeneID\tGSM1\tGSM2\n" + "1\t5\t6\n" * 50_000
    async with _client({counts_url("GSE1"): gzip.compress(body.encode())}, []) as http:
        assert await GeoClient(http).count_columns("GSE1") == ["GSM1", "GSM2"]


async def test_count_columns_follows_a_renamed_file_and_reports_none_when_absent() -> None:
    other = "GSE1_raw_counts_GRCh39_NCBI.tsv.gz"
    files = {
        f"{FTP}/rnaseq_counts/GSEnnn/": f'<a href="{other}">x</a>'.encode(),
        counts_url("GSE1", other): gzip.compress(b"GeneID\tGSM7\n1\t2\n"),
    }
    seen: list[str] = []
    async with _client(files, seen) as http:
        geo = GeoClient(http)
        assert await geo.count_columns("GSE1") == ["GSM7"]
        assert await geo.count_columns("GSE2") is None
    assert seen[0] == counts_url("GSE1")


async def test_record_methods_refuse_non_series_accessions() -> None:
    async with _client({}, []) as http:
        with pytest.raises(ValueError):
            await GeoClient(http).series_record("GSM1")
        with pytest.raises(ValueError):
            await GeoClient(http).count_columns("GSE1 OR 1")
