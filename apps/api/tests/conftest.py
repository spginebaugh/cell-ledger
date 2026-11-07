"""Shared fixtures: a fake GEO host, an in-memory object store and a poll helper."""

import gzip
import time
from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from cell_ledger.geo.fetch import ANNOTATION_URL, counts_url, soft_url
from cell_ledger_api.storage import MemoryStore

SOFT = """\
^SERIES = GSE100001
!Series_title = Drug X in PANC-1 cells
^SAMPLE = GSM1
!Sample_organism_ch1 = Homo sapiens
!Sample_library_strategy = RNA-Seq
^SAMPLE = GSM2
!Sample_organism_ch1 = Mus musculus
!Sample_library_strategy = RNA-Seq
"""
GEO_FILES = {
    ANNOTATION_URL: gzip.compress(b"GeneID\tSymbol\n1\tA1BG\n"),
    counts_url("GSE100001"): gzip.compress(b"GeneID\tGSM1\tGSM2\n1\t5\t6\n"),
    soft_url("GSE100001"): gzip.compress(SOFT.encode()),
    # GSE100003: counts exist, the SOFT file does not -> the download error path.
    counts_url("GSE100003"): gzip.compress(b"GeneID\tGSM1\n1\t5\n"),
}


def fake_geo(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "esearch.fcgi" in url:
        return httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}})
    if url in GEO_FILES:
        return httpx.Response(200, content=b"" if request.method == "HEAD" else GEO_FILES[url])
    return httpx.Response(404)


@pytest.fixture
def geo_transport() -> httpx.MockTransport:
    return httpx.MockTransport(fake_geo)


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


def _wait_collected(client: TestClient, sid: str, timeout: float = 10) -> dict:  # type: ignore[type-arg]
    """Poll listDatasets the way the UI does, until nothing is pending."""
    deadline = time.monotonic() + timeout
    while True:
        body = client.get(f"/api/sessions/{sid}/datasets").json()
        if not body["pending"]:
            return body
        assert time.monotonic() < deadline, f"still pending: {body['pending']}"
        time.sleep(0.05)


@pytest.fixture
def wait_collected() -> Callable[..., dict]:  # type: ignore[type-arg]
    return _wait_collected
