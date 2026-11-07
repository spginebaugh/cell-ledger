from .conftest import ApiFactory


def test_health_reports_database(api: ApiFactory) -> None:
    with api() as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["api_version"] and body["core_version"]
