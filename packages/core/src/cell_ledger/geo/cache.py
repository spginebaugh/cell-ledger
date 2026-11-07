"""Bounded, rate-limited downloads; offline cache misses are explicit failures."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from cell_ledger.geo.models import GeoError

_rate_lock = threading.Lock()
_next_request = 0.0


class CachedClient:
    def __init__(
        self,
        directory: Path,
        *,
        offline: bool = False,
        api_key: str | None = None,
        max_bytes: int = 500_000_000,
        client: httpx.AsyncClient | None = None,
    ):
        self.directory = directory
        self.offline = offline
        self.api_key = api_key
        self.max_bytes = max_bytes
        self.client = client
        self._lock = asyncio.Lock()

    async def get(
        self, url: str, params: dict[str, str] | None = None, *, _redirects: int = 0
    ) -> tuple[bytes, dict]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "www.ncbi.nlm.nih.gov",
            "eutils.ncbi.nlm.nih.gov",
            "ftp.ncbi.nlm.nih.gov",
        }:
            raise GeoError("Only HTTPS downloads from NCBI are supported")
        request_url = str(httpx.URL(url).copy_merge_params(params or {}))
        key = hashlib.sha256(request_url.encode()).hexdigest()
        file = self.directory / f"{key}.bin"
        meta = self.directory / f"{key}.json"
        if file.exists() and meta.exists():
            payload = file.read_bytes()
            provenance = json.loads(meta.read_text())
            if hashlib.sha256(payload).hexdigest() != provenance["sha256"]:
                raise GeoError(f"Cache checksum mismatch: {file.name}")
            if len(payload) > self.max_bytes:
                raise GeoError("Cached download exceeds the configured size limit")
            return payload, provenance
        if self.offline:
            raise GeoError(f"Offline cache miss: {request_url}")
        request_params = dict(httpx.URL(request_url).params)
        if self.api_key and parsed.hostname == "eutils.ncbi.nlm.nih.gov":
            request_params["api_key"] = self.api_key
        own_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=60, follow_redirects=False)
        try:
            for attempt in range(3):
                try:
                    async with self._lock:
                        global _next_request
                        with _rate_lock:
                            now = time.monotonic()
                            delay = max(0, _next_request - now)
                            _next_request = now + delay + (0.11 if self.api_key else 0.35)
                        await asyncio.sleep(delay)
                        async with client.stream("GET", url, params=request_params) as response:
                            response.raise_for_status()
                            if int(response.headers.get("content-length", 0)) > self.max_bytes:
                                raise GeoError("Download exceeds the configured size limit")
                            content = bytearray()
                            async for chunk in response.aiter_bytes():
                                content.extend(chunk)
                                if len(content) > self.max_bytes:
                                    raise GeoError("Download exceeds the configured size limit")
                    payload = bytes(content)
                    if (
                        b"Checking your browser" in payload[:50_000]
                        or b"recaptcha" in payload[:50_000]
                    ):
                        raise GeoError("NCBI returned a browser challenge instead of data")
                    break
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.is_redirect:
                        if _redirects >= 3:
                            raise GeoError("Too many download redirects") from exc
                        location = urljoin(request_url, exc.response.headers.get("location", ""))
                        payload, _ = await self.get(location, _redirects=_redirects + 1)
                        break
                    retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                        exc.response.status_code == 429 or exc.response.status_code >= 500
                    )
                    if attempt == 2 or not retryable:
                        raise GeoError(f"NCBI retrieval failed for {request_url}") from exc
                    await asyncio.sleep(2**attempt)
            else:
                raise GeoError("Download retry limit exceeded")
            provenance = {
                "url": request_url,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "md5": hashlib.md5(payload, usedforsecurity=False).hexdigest(),
            }
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = file.with_suffix(".tmp")
            temporary.write_bytes(payload)
            temporary.replace(file)
            meta.write_text(json.dumps(provenance, indent=2))
            return payload, provenance
        finally:
            if own_client:
                await client.aclose()
