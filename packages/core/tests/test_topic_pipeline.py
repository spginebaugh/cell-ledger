import json
from pathlib import Path

import httpx

from cell_ledger.geo.cache import CachedClient
from cell_ledger.pipeline import RunRequest, run_pipeline


async def test_no_results_writes_honest_bundle(tmp_path: Path):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"esearchresult": {"idlist": []}})
        )
    ) as transport:
        client = CachedClient(tmp_path / "cache", client=transport)
        result = await run_pipeline(RunRequest(topic="IFNG macrophages"), tmp_path / "out", client)
    assert result["datasets"] == []
    assert json.loads((tmp_path / "out/contrasts.json").read_text()) == []
    assert "No series found" in (tmp_path / "out/questions.md").read_text()


async def test_out_of_scope_never_accesses_network(tmp_path: Path):
    client = CachedClient(tmp_path / "cache", offline=True)
    result = await run_pipeline(RunRequest(topic="mouse single-cell"), tmp_path / "out", client)
    assert result["status"] == "unsupported"
    assert not result["queries"]


async def test_offline_miss_is_error_not_empty_success(tmp_path: Path):
    result = await run_pipeline(
        RunRequest(topic="macrophage"),
        tmp_path / "out",
        CachedClient(tmp_path / "cache", offline=True),
    )
    assert result["status"] == "error"
    assert "Offline cache miss" in (tmp_path / "out/questions.md").read_text()


async def test_download_query_and_ncbi_redirect_preserved(tmp_path: Path):
    calls = []

    def response(request):
        calls.append(request)
        if request.url.host == "www.ncbi.nlm.nih.gov":
            assert request.url.params["file"] == "counts.gz"
            return httpx.Response(
                301, headers={"Location": "https://ftp.ncbi.nlm.nih.gov/counts.gz"}
            )
        return httpx.Response(200, content=b"matrix")

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as transport:
        client = CachedClient(tmp_path / "cache", client=transport)
        url = "https://www.ncbi.nlm.nih.gov/geo/download/?file=counts.gz"
        content, _ = await client.get(url)
        assert content == b"matrix"
        client.offline = True
        assert (await client.get(url))[0] == content
        assert len(calls) == 2


async def test_full_pipeline_and_offline_replay(tmp_path: Path):
    import numpy as np
    import pandas as pd

    from cell_ledger.bundle import load_bundle

    samples = [f"GSM{i}" for i in range(1, 7)]
    soft = "^SERIES = GSE1\n!Series_title = Synthetic integration fixture\n"
    soft += "".join(f"!Series_sample_id = {gsm}\n" for gsm in samples)
    for i, gsm in enumerate(samples):
        soft += (
            f"^SAMPLE = {gsm}\n!Sample_title = sample {i}\n"
            "!Sample_organism_ch1 = Homo sapiens\n!Sample_library_strategy = RNA-Seq\n"
            "!Sample_platform_id = GPL1\n"
            f"!Sample_characteristics_ch1 = condition: {'case' if i < 3 else 'control'}\n"
            f"!Sample_characteristics_ch1 = donor: {i}\n"
        )
    rng = np.random.default_rng(51)
    matrix = pd.DataFrame(
        rng.negative_binomial(20, 0.001, (200, 6)),
        index=[str(i) for i in range(200)],
        columns=samples,
    )
    matrix.index.name = "gene_id"

    def respond(request):
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["1"]}})
        if request.url.path.endswith("esummary.fcgi"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "1": {
                            "accession": "GSE1",
                            "title": "Synthetic integration fixture",
                            "n_samples": 6,
                        }
                    }
                },
            )
        if request.url.path.endswith("acc.cgi"):
            return httpx.Response(200, text=soft)
        if request.url.params.get("format") == "file":
            return httpx.Response(200, text=matrix.to_csv(sep="\t"))
        return httpx.Response(
            200,
            text='<a href="/geo/download/?type=rnaseq_counts&amp;'
            'acc=GSE1&amp;format=file&amp;file=GSE1_raw_counts_test.tsv">counts</a>',
        )

    request = RunRequest(topic="synthetic fixture", case="case", control="control")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
        client = CachedClient(tmp_path / "cache", client=transport)
        live = await run_pipeline(request, tmp_path / "live", client)
        client.offline = True
        offline = await run_pipeline(request, tmp_path / "offline", client)
    assert live["datasets"] == offline["datasets"]
    assert live["datasets"][0]["status"] == "de_ready"
    counts, metadata, _, _ = load_bundle(tmp_path / "live/datasets/GSE1")
    assert counts.shape == (6, 200)
    assert metadata.loc["GSM1", "group"] == "case"
    assert metadata.loc["GSM6", "group"] == "control"

    # Execute the exact exported script on synthetic data to check the handoff.
    import subprocess
    import sys

    analysis = subprocess.run(
        [sys.executable, str(tmp_path / "live/run_deseq.py")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert analysis.returncode == 0, analysis.stderr
    results = pd.read_csv(tmp_path / "live/datasets/GSE1/deseq_results.tsv", sep="\t")
    assert "padj" in results
    assert len(results) == 200


async def test_model_cannot_add_unfetched_accessions(tmp_path: Path):
    from pydantic import BaseModel

    from cell_ledger.interpretation import Interpreter, SearchPlan

    class UnreliableInterpreter(Interpreter):
        async def extract[T: BaseModel](self, task: str, data: dict, schema: type[T]) -> T:
            if schema is SearchPlan:
                return schema.model_validate({"queries": ["human macrophage"]})
            return schema.model_validate(
                {"candidates": [{"gse": "GSE999999", "score": 1, "reason": "Invented candidate"}]}
            )

    def respond(request):
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["1"]}})
        return httpx.Response(200, json={"result": {"1": {"accession": "GSE1"}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
        result = await run_pipeline(
            RunRequest(topic="human macrophage"),
            tmp_path / "out",
            CachedClient(tmp_path / "cache", client=transport),
            interpreter=UnreliableInterpreter("test", "", tmp_path / "model"),
        )
    assert result["status"] == "error"
    assert not result["datasets"]
    assert not (tmp_path / "out/datasets/GSE999999").exists()


async def test_ineligible_unknown_samples_do_not_trigger_clarification(tmp_path, monkeypatch):
    import cell_ledger.pipeline as pipeline
    from cell_ledger.geo.client import GeoSeriesHit
    from cell_ledger.geo.models import GeoSample, GeoSeries

    source = GeoSeries(
        gse="GSE1",
        source_url="https://example.org",
        samples=[
            GeoSample(
                gsm="GSM1",
                fields={
                    "organism_ch1": ["Homo sapiens"],
                    "library_strategy": ["RNA-Seq"],
                    "characteristics_ch1": ["treatment: IFNG"],
                },
            ),
            GeoSample(
                gsm="GSM2",
                fields={
                    "organism_ch1": ["Homo sapiens"],
                    "library_strategy": ["RNA-Seq"],
                    "characteristics_ch1": ["treatment: none"],
                },
            ),
            GeoSample(
                gsm="GSM3",
                fields={"organism_ch1": ["Mus musculus"], "library_strategy": ["RNA-Seq"]},
            ),
        ],
    )

    async def search(*args, **kwargs):
        return [
            GeoSeriesHit(
                gse="GSE1",
                title="Mixed species",
                summary="",
                taxa=[],
                series_types=[],
                pubmed_ids=[],
                matched_queries=[],
                n_samples=3,
                published=None,
            )
        ]

    async def metadata(*args):
        return source

    async def sources(*args):
        return [{"url": "https://example.org/counts.tsv", "kind": "counts", "rule": "fixture"}]

    class Client(CachedClient):
        async def get(self, url, params=None, *, _redirects=0):
            return b"gene\tGSM1\tGSM2\ng1\t1000000\t2000000\n", {}

    async def ask(*args):
        raise AssertionError("Ineligible mouse records must not ask for human group labels")

    monkeypatch.setattr(pipeline, "search_geo", search)
    monkeypatch.setattr(pipeline, "get_series_metadata", metadata)
    monkeypatch.setattr(pipeline, "expression_sources", sources)
    result = await run_pipeline(
        RunRequest(topic="human IFNG", case="IFNG", control="none"),
        tmp_path / "run",
        Client(tmp_path / "cache"),
        ask=ask,
    )
    assert result["status"] == "complete"
    assert result["datasets"][0]["samples"] == 2
    assert result["clarifications"] == []


async def test_live_web_hits_merge_deduplicate_and_obey_year(tmp_path, monkeypatch):
    from datetime import date

    from cell_ledger import pipeline
    from cell_ledger.geo.client import GeoSeriesHit
    from cell_ledger.geo.models import GeoError

    def hit(number, year):
        return GeoSeriesHit(
            gse=f"GSE{number}",
            title="Study",
            summary="",
            taxa=["Homo sapiens"],
            series_types=[],
            n_samples=6,
            published=date(year, 1, 1),
            pubmed_ids=[],
            matched_queries=[],
        )

    from cell_ledger.interpretation import CandidateScore, Interpreter, Ranking, SearchPlan

    class InterpreterStub(Interpreter):
        model = "fixture"

        async def extract(self, task, data, schema):
            json.dumps(data)  # Publication dates must be JSON-safe for model requests.
            if schema is SearchPlan:
                return SearchPlan(queries=[data["topic"]])
            return Ranking(
                candidates=[
                    CandidateScore(gse=hit["gse"], score=0.1, reason="fixture")
                    for hit in data["candidates"]
                ]
            )

    calls = []

    async def web(topic):
        calls.append(topic)
        return [hit(100, 2024), hit(101, 2010)]

    async def geo(*args, **kwargs):
        return [hit(100, 2024), hit(102, 2023)]

    async def metadata(*args):
        raise GeoError("Fixture: stop before downloading")

    monkeypatch.setattr(pipeline, "search_geo", geo)
    monkeypatch.setattr(pipeline, "get_series_metadata", metadata)
    result = await run_pipeline(
        RunRequest(topic="human IFNG", since=2020),
        tmp_path / "out",
        CachedClient(tmp_path / "cache"),
        web_search=web,
        interpreter=InterpreterStub("fixture", "test-only", tmp_path / "interpretations"),
    )
    assert calls == ["human IFNG"]
    assert result["ranking"] == ["GSE100", "GSE102"]
    assert result["discovered_count"] == 2


async def test_offline_and_frozen_runs_never_call_web(tmp_path, monkeypatch):
    from cell_ledger import pipeline

    async def web(topic):
        raise AssertionError("Offline run contacted Exa")

    async def geo(*args, **kwargs):
        return []

    monkeypatch.setattr(pipeline, "search_geo", geo)
    for mode in ("offline", "frozen"):
        result = await run_pipeline(
            RunRequest(topic="human IFNG", offline=True),
            tmp_path / mode,
            CachedClient(tmp_path / "cache", offline=True),
            web_search=web,
            **({"candidate_pool": [], "snapshot_sha256": "fixture"} if mode == "frozen" else {}),
        )
        assert result["status"] == "complete"
