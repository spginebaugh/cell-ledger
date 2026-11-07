"""Frozen runner regressions; no model credentials or live sources are used."""

import json

import pytest

from cell_ledger.geo.models import GeoSample, GeoSeries
from evals.contracts import Snapshot, SourceRecord, digest
from evals.specialist import run


async def test_public_frozen_runner_preserves_all_reported_organisms(tmp_path, monkeypatch):
    source = SourceRecord(
        gse="GSE1",
        url="fixture://synthetic",
        retrieved_at="synthetic",
        fields={"title": ["Mixed-organism test"]},
        samples={
            "GSM1": {"organism_ch1": ["Homo sapiens"]},
            "GSM2": {"organism_ch1": ["Mus musculus"]},
            "GSM3": {"organism_ch1": ["Homo sapiens"]},
            "GSM4": {},
        },
    )
    snapshot = Snapshot(data_kind="synthetic", records={"GSE1": source})
    task = {"id": "fixture", "prompt": "human bulk", "constraints": {"max_datasets": 1}}
    task["prompt_sha256"] = digest({"prompt": task["prompt"], "constraints": task["constraints"]})
    task["candidate_gses"] = ["GSE1"]
    (tmp_path / "tasks.json").write_text(json.dumps([task]))
    (tmp_path / "snapshot.json").write_text(snapshot.model_dump_json())
    metadata = GeoSeries(
        gse=source.gse,
        fields=source.fields,
        samples=[GeoSample(gsm=gsm, fields=fields) for gsm, fields in source.samples.items()],
        source_url=source.url,
    )

    async def retrieve(client, gse):
        assert client.offline and gse == "GSE1"
        return metadata

    observed = []

    async def pipeline(*args, **kwargs):
        assert kwargs["interpreter"] is None
        observed.extend(kwargs["candidate_pool"])
        return {"status": "synthetic"}

    monkeypatch.setattr("evals.specialist.get_series_metadata", retrieve)
    monkeypatch.setattr("evals.specialist.run_pipeline", pipeline)
    await run(tmp_path, "fixture", tmp_path / "out", tmp_path / "cache", None)
    assert observed[0].taxa == ["Homo sapiens", "Mus musculus"]
    assert observed[0].mixed_organism
    assert observed[0].n_samples == 4  # Missing organism metadata is not invented or discarded.


async def test_legacy_runner_identifies_stage_specific_contract(tmp_path):
    (tmp_path / "tasks.json").write_text(json.dumps([{"id": "pilot", "stage": "discovery"}]))
    with pytest.raises(ValueError, match=r"Stage-specific tasks use evals\.pilot"):
        await run(tmp_path, "pilot", tmp_path / "out", tmp_path / "cache", None)
