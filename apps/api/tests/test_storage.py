"""SupabaseStore request shapes, checked against a fake Storage API."""

import json

import httpx

from cell_ledger_api.storage import SupabaseStore

BASE = "https://proj.supabase.co/storage/v1"


def _store(handler) -> tuple[SupabaseStore, httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SupabaseStore(http, "https://proj.supabase.co/", "sb_secret_x", "sessions"), http


async def test_put_sends_upsert_with_secret_key() -> None:
    seen: list[httpx.Request] = []

    def handle(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return httpx.Response(200, json={})

    store, http = _store(handle)
    async with http:
        await store.put("s1/geo/GSE1/dataset.json", b"{}", "application/json")
    (r,) = seen
    assert str(r.url) == f"{BASE}/object/sessions/s1/geo/GSE1/dataset.json"
    assert r.headers["apikey"] == "sb_secret_x" and r.headers["x-upsert"] == "true"
    assert r.headers["authorization"] == "Bearer sb_secret_x"


async def test_delete_prefix_walks_folders() -> None:
    tree = {
        "s1": [{"name": "geo", "id": None}],
        "s1/geo": [{"name": "GSE1", "id": None}],
        "s1/geo/GSE1": [{"name": "a.gz", "id": "1"}, {"name": "dataset.json", "id": "2"}],
    }
    deleted: list[str] = []

    def handle(r: httpx.Request) -> httpx.Response:
        body = json.loads(r.content)
        if r.url.path.endswith("/object/list/sessions"):
            return httpx.Response(200, json=tree.get(body["prefix"], []))
        assert r.method == "DELETE"
        deleted.extend(body["prefixes"])
        return httpx.Response(200, json=[])

    store, http = _store(handle)
    async with http:
        assert await store.delete_prefix("s1") == 2
    assert sorted(deleted) == ["s1/geo/GSE1/a.gz", "s1/geo/GSE1/dataset.json"]


async def test_signed_url_is_absolute_and_missing_is_none() -> None:
    def handle(r: httpx.Request) -> httpx.Response:
        if "missing" in r.url.path:
            return httpx.Response(400, json={"error": "not_found"})
        return httpx.Response(200, json={"signedURL": "/object/sign/sessions/s1/x?token=t"})

    store, http = _store(handle)
    async with http:
        assert await store.signed_url("s1/x", 60) == f"{BASE}/object/sign/sessions/s1/x?token=t"
        assert await store.signed_url("s1/missing", 60) is None
