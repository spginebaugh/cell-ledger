"""Supabase Storage: the durable copy of every session file.

Paths are bucket-relative, e.g. ``<session>/geo/<GSE>/<file>`` and
``<session>/runs/<GSE>/<contrast>/<file>``. The API machine's disk is only a cache: a file
that is not on disk is pulled back from here before the pipeline needs it, and the browser
downloads through short-lived signed URLs so large files never stream through the API.

Talks to the Storage REST API with the backend's secret key over its own httpx client; the
same code runs against the local stack (``mise run supabase:start``) and the cloud.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import quote

import httpx

CHUNK = 1 << 20
PAGE = 1000


class StorageUnavailable(RuntimeError):
    pass


class SupabaseStore:
    def __init__(self, url: str, secret_key: str, bucket: str) -> None:
        self._bucket = bucket
        self.base_url = f"{url.rstrip('/')}/storage/v1"
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"apikey": secret_key, "Authorization": f"Bearer {secret_key}"},
            timeout=httpx.Timeout(30, read=600),
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def check(self) -> None:
        """Fail fast at startup when the key or bucket is wrong."""
        try:
            r = await self._http.get(f"/bucket/{self._bucket}")
        except httpx.HTTPError as e:
            raise StorageUnavailable(f"Supabase Storage unreachable at {self.base_url}: {e}") from e
        if r.status_code != 200:
            raise StorageUnavailable(
                f"Supabase bucket {self._bucket!r} not accessible ({r.status_code}): {r.text}"
            )

    def _object(self, path: str) -> str:
        return f"/object/{self._bucket}/{quote(path)}"

    async def put_file(self, path: str, file: Path, content_type: str) -> None:
        # An explicit Content-Length makes httpx stream the body instead of chunking it,
        # which Supabase Storage needs for a plain object upload.
        size = file.stat().st_size

        async def body() -> AsyncIterator[bytes]:
            with file.open("rb") as f:
                while chunk := f.read(CHUNK):
                    yield chunk

        r = await self._http.post(
            self._object(path),
            content=body(),
            headers={"Content-Type": content_type, "Content-Length": str(size), "x-upsert": "true"},
        )
        r.raise_for_status()

    async def get_file(self, path: str, dest: Path) -> bool:
        """Stream an object to ``dest`` atomically. False when it does not exist."""
        async with self._http.stream("GET", self._object(path)) as r:
            if r.status_code in (400, 404):
                return False
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            with tmp.open("wb") as f:
                async for chunk in r.aiter_bytes():
                    f.write(chunk)
            tmp.replace(dest)
        return True

    async def list(self, prefix: str) -> list[str]:
        """Every object path under ``prefix`` (Supabase lists one folder level at a time)."""
        paths: list[str] = []
        folders = [prefix.rstrip("/")]
        while folders:
            folder = folders.pop()
            offset = 0
            while True:
                r = await self._http.post(
                    f"/object/list/{self._bucket}",
                    json={"prefix": folder, "limit": PAGE, "offset": offset},
                )
                r.raise_for_status()
                entries = r.json()
                for e in entries:
                    full = f"{folder}/{e['name']}"
                    # Folders come back without an id.
                    (paths if e.get("id") else folders).append(full)
                if len(entries) < PAGE:
                    break
                offset += PAGE
        return paths

    async def delete_prefix(self, prefix: str) -> int:
        paths = await self.list(prefix)
        for i in range(0, len(paths), PAGE):
            r = await self._http.request(
                "DELETE", f"/object/{self._bucket}", json={"prefixes": paths[i : i + PAGE]}
            )
            r.raise_for_status()
        return len(paths)

    async def signed_urls(self, paths: list[str], expires_in: int) -> dict[str, str]:
        """Sign many objects in one request; paths that do not exist are left out."""
        if not paths:
            return {}
        r = await self._http.post(
            f"/object/sign/{self._bucket}", json={"expiresIn": expires_in, "paths": paths}
        )
        if r.status_code == 404:  # a very old Storage without the batch endpoint
            out = {}
            for p in paths:
                url = await self.signed_url(p, expires_in)
                if url:
                    out[p] = url
            return out
        r.raise_for_status()
        out: dict[str, str] = {}
        for entry in r.json():
            signed = entry.get("signedURL")
            if signed and not entry.get("error"):
                out[entry["path"]] = f"{self.base_url}{signed}"
        return out

    async def signed_url(self, path: str, expires_in: int) -> str | None:
        r = await self._http.post(
            f"/object/sign/{self._bucket}/{quote(path)}", json={"expiresIn": expires_in}
        )
        if r.status_code in (400, 404):  # Supabase answers 400 for a missing object
            return None
        r.raise_for_status()
        return f"{self.base_url}{r.json()['signedURL']}"
