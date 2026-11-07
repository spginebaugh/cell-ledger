"""SupabaseStore against the real local Storage API."""

import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest

from cell_ledger_api.settings import Settings
from cell_ledger_api.storage import StorageUnavailable, SupabaseStore

from .conftest import store_for


@pytest.fixture
async def store(settings_for: Callable[..., Settings]) -> AsyncIterator[SupabaseStore]:
    s = store_for(settings_for())
    prefix = f"test-{uuid.uuid4().hex}"
    s.prefix = prefix  # type: ignore[attr-defined]
    try:
        yield s
    finally:
        await s.delete_prefix(prefix)
        await s.aclose()


async def test_check_passes_for_the_real_bucket_and_fails_for_a_wrong_one(
    settings_for: Callable[..., Settings],
) -> None:
    cfg = settings_for()
    good = store_for(cfg)
    bad = SupabaseStore(cfg.supabase_url, cfg.supabase_secret_key.get_secret_value(), "nope")
    unreachable = SupabaseStore("http://127.0.0.1:9", "x", "sessions")
    try:
        await good.check()
        with pytest.raises(StorageUnavailable, match="nope"):
            await bad.check()
        with pytest.raises(StorageUnavailable, match="unreachable"):
            await unreachable.check()
    finally:
        await good.aclose()
        await bad.aclose()
        await unreachable.aclose()


async def test_put_get_sign_list_delete_roundtrip(store: SupabaseStore, tmp_path: Path) -> None:
    prefix: str = store.prefix  # type: ignore[attr-defined]
    big = tmp_path / "counts.tsv.gz"
    big.write_bytes(b"x" * (3 * (1 << 20) + 17))  # several upload chunks plus a tail
    small = tmp_path / "dataset.json"
    small.write_text("{}")

    await store.put_file(f"{prefix}/geo/GSE1/counts.tsv.gz", big, "application/gzip")
    await store.put_file(f"{prefix}/geo/GSE1/dataset.json", small, "application/json")
    await store.put_file(f"{prefix}/geo/GSE1/dataset.json", small, "application/json")  # upsert

    assert sorted(await store.list(prefix)) == [
        f"{prefix}/geo/GSE1/counts.tsv.gz",
        f"{prefix}/geo/GSE1/dataset.json",
    ]

    back = tmp_path / "back" / "counts.tsv.gz"
    assert await store.get_file(f"{prefix}/geo/GSE1/counts.tsv.gz", back)
    assert back.read_bytes() == big.read_bytes()
    assert not await store.get_file(f"{prefix}/geo/GSE1/missing", tmp_path / "x")
    assert not (tmp_path / "x").exists()

    url = await store.signed_url(f"{prefix}/geo/GSE1/dataset.json", 60)
    assert url is not None and url.startswith(f"{store.base_url}/object/sign/")
    assert httpx.get(url).content == b"{}"
    assert await store.signed_url(f"{prefix}/geo/GSE1/missing", 60) is None

    assert await store.delete_prefix(prefix) == 2
    assert await store.list(prefix) == []
