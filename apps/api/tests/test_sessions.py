"""Session endpoints end to end: fake GEO host, real local Postgres and Storage."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from cell_ledger_api.settings import Settings

from .conftest import ApiFactory, store_for

SIGN_PREFIX = "/storage/v1/object/sign/sessions/"


def test_collect_list_link_and_delete(
    client: TestClient,
    tmp_path: Path,
    settings_for: Callable[..., Settings],
    wait_collected: Callable[..., list[dict]],  # type: ignore[type-arg]
) -> None:
    sid = client.post("/api/sessions").json()["id"]
    assert client.get(f"/api/sessions/{sid}").json()["id"] == sid

    r = client.post(f"/api/sessions/{sid}/datasets", json={"gses": ["GSE100001", "GSE100002"]})
    assert r.status_code == 202
    assert [d["gse"] for d in r.json()] == ["GSE100001", "GSE100002"]
    # Asking again for something already requested does not create a second row.
    r = client.post(f"/api/sessions/{sid}/datasets", json={"gses": ["GSE100001"]})
    assert r.status_code == 202 and len(r.json()) == 2

    ready, missing = wait_collected(client, sid)
    assert ready["status"] == "ready" and ready["uploaded"] and ready["finished_at"]
    assert ready["record"]["n_eligible"] == 1
    assert "GSE100001_family.soft.gz" in ready["files"]
    assert missing["status"] == "excluded"
    assert missing["record"]["exclusions"] == ["no_ncbi_counts"]

    # Local cache in the pipeline's layout plus the shared annotation table.
    local = tmp_path / "sessions" / sid / "geo" / "GSE100001"
    counts = local / "GSE100001_raw_counts_GRCh38.p13_NCBI.tsv.gz"
    assert counts.exists()
    assert (tmp_path / "geo" / "annotation" / "Human.GRCh38.p13.annot.tsv.gz").exists()

    # The signed URL really downloads the mirrored object from Storage.
    link = client.get(f"/api/sessions/{sid}/datasets/GSE100001/files/{counts.name}")
    assert link.status_code == 200 and SIGN_PREFIX in link.json()["url"]
    assert httpx.get(link.json()["url"]).content == counts.read_bytes()
    assert client.get(f"/api/sessions/{sid}/datasets/GSE100001/files/nope.txt").status_code == 404

    assert client.delete(f"/api/sessions/{sid}").status_code == 204
    assert not (tmp_path / "sessions" / sid).exists()
    assert client.get(f"/api/sessions/{sid}/datasets").status_code == 404
    assert client.get(f"/api/sessions/{sid}").status_code == 404
    assert _objects(settings_for(), sid) == []


def _objects(cfg: Settings, prefix: str) -> list[str]:
    import asyncio

    async def go() -> list[str]:
        store = store_for(cfg)
        try:
            return await store.list(prefix)
        finally:
            await store.aclose()

    return asyncio.run(go())


def test_failed_download_is_recorded_not_raised(
    client: TestClient,
    wait_collected: Callable[..., list[dict]],  # type: ignore[type-arg]
) -> None:
    """A series whose counts exist but whose SOFT file 404s ends up failed, not stuck."""
    sid = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{sid}/datasets", json={"gses": ["GSE100003"]})
    (d,) = wait_collected(client, sid)
    assert d["status"] == "failed" and d["record"] is None
    assert "HTTPStatusError" in d["error"]
    # A failed dataset may be requested again (the fake host is instant, so it may already
    # have failed again by the time we look: the proof is a later finished_at).
    client.post(f"/api/sessions/{sid}/datasets", json={"gses": ["GSE100003"]})
    (again,) = wait_collected(client, sid)
    assert again["status"] == "failed" and again["finished_at"] > d["finished_at"]


def test_restart_redispatches_pending_and_gives_up_eventually(
    api: ApiFactory,
    pg: Callable[..., Any],
    wait_collected: Callable[..., list[dict]],  # type: ignore[type-arg]
) -> None:
    """Rows left pending by a dead process are collected by the next one, up to max_attempts."""
    sid = "b" * 32
    pg("insert into sessions (id) values ($1)", sid)
    pg(
        "insert into datasets (session_id, gse, status, attempts) values "
        "($1, 'GSE100001', 'pending', 0), ($1, 'GSE100003', 'pending', 2)",
        sid,
    )
    with api(max_attempts=2) as c:
        fresh, exhausted = wait_collected(c, sid)
    assert fresh["gse"] == "GSE100001" and fresh["status"] == "ready"
    assert exhausted["status"] == "failed" and "giving up" in exhausted["error"]


def test_rejects_bad_input(client: TestClient) -> None:
    sid = client.post("/api/sessions").json()["id"]
    too_many = {"gses": ["GSE1", "GSE2", "GSE3"]}
    assert client.post(f"/api/sessions/{sid}/datasets", json=too_many).status_code == 422
    assert client.post(f"/api/sessions/{sid}/datasets", json={"gses": ["GSM1"]}).status_code == 422
    assert client.get("/api/sessions/../etc/datasets").status_code == 404
    assert client.get("/api/sessions/" + "0" * 32 + "/datasets").status_code == 404
    assert client.delete("/api/sessions/" + "0" * 32).status_code == 404


def test_search_endpoint(client: TestClient) -> None:
    r = client.post("/api/geo/search", json={"queries": ["PDAC"]})
    assert r.status_code == 200
    assert r.json()["queries"][0]["query"] == "PDAC" and r.json()["hits"] == []
    assert client.post("/api/geo/search", json={"queries": []}).status_code == 422


def test_expired_sessions_swept_at_startup(
    api: ApiFactory,
    pg: Callable[..., Any],
    settings_for: Callable[..., Settings],
    tmp_path: Path,
) -> None:
    import asyncio

    sid = "a" * 32
    pg(
        "insert into sessions (id, created_at) values ($1, $2)",
        sid,
        datetime.now(UTC) - timedelta(hours=48),
    )
    pg("insert into datasets (session_id, gse, status) values ($1, 'GSE1', 'excluded')", sid)
    obj = tmp_path / "dataset.json"
    obj.write_text("{}")

    async def put() -> None:
        store = store_for(settings_for())
        try:
            await store.put_file(f"{sid}/geo/GSE1/dataset.json", obj, "application/json")
        finally:
            await store.aclose()

    asyncio.run(put())
    stale_dir = tmp_path / "sessions" / ("f" * 32)  # a cache folder with no row behind it
    stale_dir.mkdir(parents=True)

    with api(session_ttl_hours=24):
        pass
    assert pg("select 1 from sessions where id = $1", sid) == []
    assert _objects(settings_for(), sid) == []
    assert not stale_dir.exists()
