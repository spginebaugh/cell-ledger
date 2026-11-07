"""Session endpoints end to end against a fake GEO host and an in-memory store."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from cell_ledger_api.main import create_app
from cell_ledger_api.settings import Settings
from cell_ledger_api.storage import MemoryStore


@pytest.fixture
def client(tmp_path: Path, store: MemoryStore, geo_transport: httpx.MockTransport):
    cfg = Settings(_env_file=None, data_dir=tmp_path, max_datasets_per_request=2)  # type: ignore[call-arg]
    app = create_app(cfg, transport=geo_transport, store=store)
    with TestClient(app) as c:
        yield c


def test_collect_list_link_and_delete(
    client: TestClient,
    store: MemoryStore,
    tmp_path: Path,
    wait_collected: Callable[..., dict],  # type: ignore[type-arg]
) -> None:
    sid = client.post("/api/sessions").json()["id"]

    r = client.post(f"/api/sessions/{sid}/datasets", json={"gses": ["GSE100001", "GSE100002"]})
    assert r.status_code == 202
    assert r.json()["pending"] == ["GSE100001", "GSE100002"]
    # Asking again for something already pending does not queue it twice (the fake host is
    # instant, so a series may already have finished; only duplicates would be wrong).
    r = client.post(f"/api/sessions/{sid}/datasets", json={"gses": ["GSE100001"]})
    pending = r.json()["pending"]
    assert r.status_code == 202 and len(pending) == len(set(pending))

    ready, missing = wait_collected(client, sid)["datasets"]
    assert ready["record"]["status"] == "ready" and ready["uploaded"]
    assert ready["record"]["n_eligible"] == 1
    assert "GSE100001_family.soft.gz" in ready["files"]
    assert missing["record"]["exclusions"] == ["no_ncbi_counts"]
    assert client.get(f"/api/sessions/{sid}").json()["pending"] == []

    # Local copy in the pipeline's layout, shared annotation, and the storage mirror.
    local = tmp_path / "sessions" / sid / "geo" / "GSE100001"
    assert (local / "GSE100001_raw_counts_GRCh38.p13_NCBI.tsv.gz").exists()
    assert (tmp_path / "geo" / "annotation" / "Human.GRCh38.p13.annot.tsv.gz").exists()
    assert f"{sid}/geo/GSE100001/GSE100001_family.soft.gz" in store.objects
    assert f"{sid}/geo/GSE100002/dataset.json" in store.objects

    listed = client.get(f"/api/sessions/{sid}/datasets").json()["datasets"]
    assert [d["gse"] for d in listed] == ["GSE100001", "GSE100002"]

    link = client.get(f"/api/sessions/{sid}/datasets/GSE100001/files/dataset.json")
    assert link.status_code == 200 and link.json()["url"].startswith("memory://")
    assert client.get(f"/api/sessions/{sid}/datasets/GSE100001/files/nope.txt").status_code == 404

    assert client.delete(f"/api/sessions/{sid}").status_code == 204
    assert not store.objects and not (tmp_path / "sessions" / sid).exists()
    assert client.get(f"/api/sessions/{sid}/datasets").status_code == 404


def test_failed_download_is_recorded_not_raised(
    client: TestClient,
    wait_collected: Callable[..., dict],  # type: ignore[type-arg]
) -> None:
    """A series whose counts exist but whose SOFT file 404s ends up failed, not stuck."""
    sid = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{sid}/datasets", json={"gses": ["GSE100003"]})
    (d,) = wait_collected(client, sid)["datasets"]
    assert d["record"] is None and "HTTPStatusError" in d["error"]


def test_restart_marks_pending_as_interrupted(
    tmp_path: Path, store: MemoryStore, geo_transport: httpx.MockTransport
) -> None:
    sid = "b" * 32
    d = tmp_path / "sessions" / sid
    (d / "geo").mkdir(parents=True)
    info = {"id": sid, "created_at": datetime.now(UTC).isoformat(), "pending": ["GSE100001"]}
    (d / "session.json").write_text(json.dumps(info))

    cfg = Settings(_env_file=None, data_dir=tmp_path)  # type: ignore[call-arg]
    with TestClient(create_app(cfg, transport=geo_transport, store=store)) as c:
        body = c.get(f"/api/sessions/{sid}/datasets").json()
    assert body["pending"] == []
    assert body["datasets"][0]["error"] == "interrupted by server restart"


def test_rejects_bad_input(client: TestClient) -> None:
    sid = client.post("/api/sessions").json()["id"]
    too_many = {"gses": ["GSE1", "GSE2", "GSE3"]}
    assert client.post(f"/api/sessions/{sid}/datasets", json=too_many).status_code == 422
    assert client.post(f"/api/sessions/{sid}/datasets", json={"gses": ["GSM1"]}).status_code == 422
    assert client.get("/api/sessions/../etc/datasets").status_code == 404
    assert client.get("/api/sessions/" + "0" * 32 + "/datasets").status_code == 404


def test_search_endpoint(client: TestClient) -> None:
    r = client.post("/api/geo/search", json={"queries": ["PDAC"]})
    assert r.status_code == 200
    assert r.json()["queries"][0]["query"] == "PDAC" and r.json()["hits"] == []
    assert client.post("/api/geo/search", json={"queries": []}).status_code == 422


def test_expired_sessions_swept_at_startup(
    tmp_path: Path, store: MemoryStore, geo_transport: httpx.MockTransport
) -> None:
    old = tmp_path / "sessions" / ("a" * 32)
    old.mkdir(parents=True)
    created = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    (old / "session.json").write_text(json.dumps({"id": "a" * 32, "created_at": created}))
    store.objects[f"{'a' * 32}/geo/GSE1/dataset.json"] = b"{}"

    cfg = Settings(_env_file=None, data_dir=tmp_path, session_ttl_hours=24)  # type: ignore[call-arg]
    with TestClient(create_app(cfg, transport=geo_transport, store=store)):
        pass
    assert not old.exists() and not store.objects
