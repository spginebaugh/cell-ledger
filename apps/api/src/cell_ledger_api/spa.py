"""Serve the built single-page app next to the API.

Two pieces, both needed so that enabling the UI changes nothing about ``/api``:

- :class:`SpaMount` declines every request under ``/api``. Starlette treats a mount at
  ``/`` as a full match for any path, and a full match beats a method-mismatch (405) and
  pre-empts trailing-slash redirects (307). Ordering routers first does not help; the
  mount has to say "not mine" for the API namespace.
- :class:`SpaStaticFiles` falls back to ``index.html`` only for browser navigations (the
  request accepts ``text/html``). A missing ``/assets/x.js`` stays a 404 instead of an
  HTML body with a MIME-type error in the console.
"""

from __future__ import annotations

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match, Mount
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Scope

API_PREFIX = "/api"


def is_api_path(path: str) -> bool:
    return path == API_PREFIX or path.startswith(API_PREFIX + "/")


def route_path(scope: Scope) -> str:
    """The request path relative to any root_path this app is served under."""
    path: str = scope["path"]
    root: str = scope.get("root_path", "")
    if root and path.startswith(root) and (len(path) == len(root) or path[len(root)] == "/"):
        return path[len(root) :]
    return path


class SpaStaticFiles(StaticFiles):
    def __init__(self, directory: Path) -> None:
        super().__init__(directory=directory, html=True)

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            accepts_html = "text/html" in Request(scope).headers.get("accept", "")
            if exc.status_code != 404 or scope["method"] not in ("GET", "HEAD") or not accepts_html:
                raise
            return await super().get_response("index.html", scope)


class SpaMount(Mount):
    """A root mount that never matches ``/api`` or anything under it."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__("/", app=app, name="web")

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] == "http" and is_api_path(route_path(scope)):
            return Match.NONE, {}
        return super().matches(scope)
