from fastapi.testclient import TestClient

from cell_ledger_api.main import app


def test_health() -> None:
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["api_version"] and body["core_version"]
