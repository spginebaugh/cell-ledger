"""The built frontend is served from "/" when CELL_LEDGER_WEB_DIST is set, and enabling it
changes nothing about /api: same 404s, 405s and trailing-slash redirects as API-only mode."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cell_ledger_api.main import create_app
from cell_ledger_api.settings import Settings

from .conftest import local_settings

NAV = {"accept": "text/html,application/xhtml+xml,*/*;q=0.8"}  # what a browser navigation sends
API_CASES = [  # (method, path, expected status in both modes)
    ("GET", "/api/health", 200),
    ("GET", "/api/health/", 307),
    ("POST", "/api/sessions/", 307),
    ("GET", "/api/sessions", 405),
    ("GET", "/api", 404),
    ("GET", "/api/", 404),
    ("GET", "/api/nope", 404),
]


def _settings(tmp_path: Path, **kw: object) -> Settings:
    return local_settings(data_dir=tmp_path / "data", **kw)


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "a.js").write_text("console.log(1)")
    return dist


def test_api_only_when_unset(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path)), follow_redirects=False) as c:
        for method, path, expected in API_CASES:
            assert c.request(method, path, headers=NAV).status_code == expected, (method, path)
        assert c.get("/", headers=NAV).status_code == 404


def test_api_routing_identical_with_ui(tmp_path: Path, dist: Path) -> None:
    with TestClient(create_app(_settings(tmp_path, web_dist=dist)), follow_redirects=False) as c:
        for method, path, expected in API_CASES:
            r = c.request(method, path, headers=NAV)
            assert r.status_code == expected, (method, path)
            assert "text/html" not in r.headers.get("content-type", ""), (method, path)


def test_serves_spa_with_fallback(tmp_path: Path, dist: Path) -> None:
    with TestClient(create_app(_settings(tmp_path, web_dist=dist))) as c:
        assert c.get("/", headers=NAV).text == "<html>app</html>"
        assert c.get("/assets/a.js").text == "console.log(1)"
        # Client-side routes deep-link to index.html for browser navigations only.
        assert c.get("/sessions/abc", headers=NAV).text == "<html>app</html>"
        assert c.get("/sessions/abc", headers={"accept": "application/json"}).status_code == 404
        # A missing asset is a real 404, not the app shell with the wrong MIME type.
        assert c.get("/assets/missing.js").status_code == 404
        assert c.post("/sessions/abc", headers=NAV).status_code == 405


def test_missing_dist_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"index\.html"):
        create_app(_settings(tmp_path, web_dist=tmp_path / "missing"))
