"""Run endpoints against the fake pipeline subprocess (tests/fake_pipeline.py)."""

import json
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from cell_ledger_api.main import create_app
from cell_ledger_api.settings import Settings
from cell_ledger_api.storage import MemoryStore

FAKE = (sys.executable, str(Path(__file__).with_name("fake_pipeline.py")))
FIXTURE = Path(__file__).parents[3] / "packages/core/tests/fixtures/geo_examples/GSE82227.json"
DESIGN = json.loads(FIXTURE.read_text())


@pytest.fixture
def client(tmp_path: Path, store: MemoryStore, geo_transport: httpx.MockTransport):
    cfg = Settings(_env_file=None, data_dir=tmp_path, run_timeout_minutes=0.02)  # type: ignore[call-arg]
    app = create_app(cfg, transport=geo_transport, store=store, run_command=FAKE)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def collected(client: TestClient, wait_collected: Callable[..., dict]) -> str:  # type: ignore[type-arg]
    """A session holding GSE100001's counts."""
    sid = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{sid}/datasets", json={"gses": ["GSE100001"]})
    wait_collected(client, sid)
    return sid


def design_for(gse: str) -> dict:  # type: ignore[type-arg]
    """The GSE82227 fixture design, re-pointed at ``gse``."""
    d = json.loads(json.dumps(DESIGN))
    d["samplesheet"]["gse"] = gse
    d["contrasts"] = d["contrasts"][:1]
    d["contrasts"][0]["gse"] = gse
    return {"samplesheet": d["samplesheet"], "contrasts": d["contrasts"], "genes": ["CXCL9"]}


def wait_runs(client: TestClient, sid: str, timeout: float = 10) -> list[dict]:  # type: ignore[type-arg]
    deadline = time.monotonic() + timeout
    while True:
        runs = client.get(f"/api/sessions/{sid}/runs").json()
        if runs and all(r["status"] != "running" for r in runs):
            return runs
        assert time.monotonic() < deadline, runs
        time.sleep(0.05)


def test_run_completes_and_uploads(
    client: TestClient, store: MemoryStore, tmp_path: Path, collected: str
) -> None:
    sid = collected
    r = client.post(f"/api/sessions/{sid}/runs", json=design_for("GSE100001"))
    assert r.status_code == 202
    (started,) = r.json()
    assert started["status"] == "running" and started["contrast"] == "ifng_vs_media_24h"
    # Starting the same GSE again while it runs is refused.
    again = client.post(f"/api/sessions/{sid}/runs", json=design_for("GSE100001"))
    assert again.status_code == 409

    (done,) = wait_runs(client, sid)
    assert done["status"] == "complete" and done["report"]["params"]["genes"] == "CXCL9"
    assert done["uploaded"] and sorted(done["files"]) == ["figures/pca.png", "report.json"]
    assert f"{sid}/runs/GSE100001/ifng_vs_media_24h/figures/pca.png" in store.objects

    link = client.get(f"/api/sessions/{sid}/runs/GSE100001/ifng_vs_media_24h/files/figures/pca.png")
    assert link.status_code == 200 and link.json()["url"].startswith("memory://")
    log = (tmp_path / "sessions" / sid / "runs" / "GSE100001" / "run.log").read_text()
    assert "fake pipeline GSE100001" in log

    # A rerun after completion is allowed and replaces the verdict.
    rerun = client.post(f"/api/sessions/{sid}/runs", json=design_for("GSE100001"))
    assert rerun.status_code == 202
    assert wait_runs(client, sid)[0]["status"] == "complete"


def test_run_refused_without_counts(client: TestClient) -> None:
    sid = client.post("/api/sessions").json()["id"]
    r = client.post(f"/api/sessions/{sid}/runs", json=design_for("GSE100001"))
    assert r.status_code == 409 and "no collected counts" in r.json()["detail"]


def test_crash_and_timeout_are_recorded(
    client: TestClient, collected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = collected
    monkeypatch.setitem(os.environ, "FAKE_PIPELINE", "crash")
    client.post(f"/api/sessions/{sid}/runs", json=design_for("GSE100001"))
    (failed,) = wait_runs(client, sid)
    assert failed["status"] == "failed" and "exited with code 2" in failed["error"]

    monkeypatch.setitem(os.environ, "FAKE_PIPELINE", "hang")
    client.post(f"/api/sessions/{sid}/runs", json=design_for("GSE100001"))
    (killed,) = wait_runs(client, sid)
    assert killed["status"] == "failed" and "killed after" in killed["error"]


def test_restart_marks_running_as_interrupted(
    tmp_path: Path, store: MemoryStore, geo_transport: httpx.MockTransport
) -> None:
    sid = "c" * 32
    run = tmp_path / "sessions" / sid / "runs" / "GSE1"
    (run / "done").mkdir(parents=True)
    (run / ".a.tmp-123").mkdir()  # the pipeline's in-progress work dir; never a contrast
    now = datetime.now(UTC).isoformat()  # recent, or the startup sweep removes the session
    (tmp_path / "sessions" / sid / "session.json").write_text(
        json.dumps({"id": sid, "created_at": now})
    )
    (run / "running.json").write_text(json.dumps({"started_at": now, "contrasts": ["a", "done"]}))
    # Not a valid AnalysisReport: the status endpoint must report that, not crash.
    (run / "done" / "report.json").write_text(json.dumps({"gse": "GSE1", "status": "complete"}))
    cfg = Settings(_env_file=None, data_dir=tmp_path)  # type: ignore[call-arg]
    with TestClient(create_app(cfg, transport=geo_transport, store=store)) as c:
        runs = {r["contrast"]: r for r in c.get(f"/api/sessions/{sid}/runs").json()}
    assert runs["a"]["status"] == "failed" and "restart" in runs["a"]["error"]
    assert not (run / "running.json").exists()
    assert runs["done"]["status"] == "failed" and "unreadable report" in runs["done"]["error"]
    assert set(runs) == {"a", "done"}
