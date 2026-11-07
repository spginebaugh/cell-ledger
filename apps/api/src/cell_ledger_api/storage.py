"""Object storage for session files.

:class:`SupabaseStore` talks to the Supabase Storage REST API with the backend's
secret key; :class:`MemoryStore` stands in for tests and for local runs without
Supabase credentials. Paths are bucket-relative, e.g. ``<session>/geo/<GSE>/<file>``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

CHUNK = 1 << 20


class ObjectStore(Protocol):
    async def list_paths(self, prefix: str) -> list[str]: ...

    async def get(self, path: str) -> bytes | None: ...

    async def put(self, path: str, data: bytes, content_type: str) -> None: ...

    async def put_file(self, path: str, file: Path, content_type: str) -> None:
        """Upload a local file without reading it into memory at once."""
        ...

    async def delete_prefix(self, prefix: str) -> int: ...

    async def signed_url(self, path: str, expires_in: int) -> str | None: ...


class SupabaseStore:
    def __init__(self, http: httpx.AsyncClient, url: str, secret_key: str, bucket: str) -> None:
        self._http = http
        self._base = f"{url.rstrip('/')}/storage/v1"
        self._bucket = bucket
        self._headers = {"apikey": secret_key, "Authorization": f"Bearer {secret_key}"}

    def _object(self, path: str) -> str:
        return f"{self._base}/object/{self._bucket}/{quote(path)}"

    async def get(self, path: str) -> bytes | None:
        r = await self._http.get(self._object(path), headers=self._headers)
        if r.status_code == 404 or (r.status_code == 400 and r.json().get("code") == "NoSuchKey"):
            return None
        r.raise_for_status()
        return r.content

    async def put(self, path: str, data: bytes, content_type: str) -> None:
        r = await self._http.post(
            self._object(path),
            content=data,
            headers={**self._headers, "Content-Type": content_type, "x-upsert": "true"},
        )
        r.raise_for_status()

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
            headers={
                **self._headers,
                "Content-Type": content_type,
                "Content-Length": str(size),
                "x-upsert": "true",
            },
        )
        r.raise_for_status()

    async def _list(self, prefix: str) -> list[str]:
        """Every object path under ``prefix`` (Supabase lists one folder level at a time)."""
        paths: list[str] = []
        folders = [prefix.rstrip("/")]
        while folders:
            folder = folders.pop()
            offset = 0
            while True:
                r = await self._http.post(
                    f"{self._base}/object/list/{self._bucket}",
                    json={"prefix": folder, "limit": 1000, "offset": offset},
                    headers=self._headers,
                )
                r.raise_for_status()
                entries = r.json()
                for e in entries:
                    full = f"{folder}/{e['name']}"
                    # Folders come back without an id.
                    (paths if e.get("id") else folders).append(full)
                if len(entries) < 1000:
                    break
                offset += 1000
        return paths

    async def list_paths(self, prefix: str) -> list[str]:
        return await self._list(prefix)

    async def delete_prefix(self, prefix: str) -> int:
        paths = await self._list(prefix)
        for i in range(0, len(paths), 1000):
            r = await self._http.request(
                "DELETE",
                f"{self._base}/object/{self._bucket}",
                json={"prefixes": paths[i : i + 1000]},
                headers=self._headers,
            )
            r.raise_for_status()
        return len(paths)

    async def signed_url(self, path: str, expires_in: int) -> str | None:
        r = await self._http.post(
            f"{self._base}/object/sign/{self._bucket}/{quote(path)}",
            json={"expiresIn": expires_in},
            headers=self._headers,
        )
        if r.status_code in (400, 404):  # Supabase answers 400 for a missing object
            return None
        r.raise_for_status()
        return f"{self._base}{r.json()['signedURL']}"


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def get(self, path: str) -> bytes | None:
        return self.objects.get(path)

    async def list_paths(self, prefix: str) -> list[str]:
        return sorted(p for p in self.objects if p.startswith(prefix.rstrip("/") + "/"))

    async def put(self, path: str, data: bytes, content_type: str) -> None:
        self.objects[path] = data

    async def put_file(self, path: str, file: Path, content_type: str) -> None:
        self.objects[path] = file.read_bytes()

    async def delete_prefix(self, prefix: str) -> int:
        doomed = [p for p in self.objects if p.startswith(prefix.rstrip("/") + "/")]
        for p in doomed:
            del self.objects[p]
        return len(doomed)

    async def signed_url(self, path: str, expires_in: int) -> str | None:
        return f"memory://{path}?expires_in={expires_in}" if path in self.objects else None
