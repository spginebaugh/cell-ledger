"""Run endpoints against the fake pipeline subprocess (tests/fake_pipeline.py), with real
local Postgres and Storage."""

import json
import os
import shutil
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from .conftest import ApiFactory

FAKE = (sys.executable, str(Path(__file__).with_name("fake_pipeline.py")))
FIXTURE = Path(__file__).parents[3] / "packages/core/tests/fixtures/geo_examples/GSE82227.json"
DESIGN = json.loads(FIXTURE.read_text())
CONTRAST = "ifng_vs_media_24h"


@pytest.fixture
def client(api: ApiFactory) -> Iterator[TestClient]:
    with api(run_command=FAKE, run_timeout_minutes=0.02) as c:
        yield c


@pytest.fixture
def collected(client: TestClient, wait_collected: Callable[..., list[dict]]) -> str:  # type: ignore[type-arg]
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


def test_run_completes_and_uploads(
    client: TestClient,
    tmp_path: Path,
    collected: str,
    wait_runs: Callable[..., list[dict]],  # type: ignore[type-arg]
) -> None:
    sid = collected
    r = client.post(f"/api/sessions/{sid}/runs", json=design_for("GSE100001"))
    assert r.status_code == 202
    (started,) = r.json()
    assert started["status"] == "running" and started["contrast"] == CONTRAST
    # Starting the same GSE again while it runs is refused.
    again = client.post(f"/api/sessions/{sid}/runs", json=design_for("GSE100001"))
    assert again.status_code == 409

    (done,) = wait_runs(client, sid)
    assert done["status"] == "complete" and done["report"]["params"]["genes"] == "CXCL9"
    assert done["uploaded"] and sorted(done["files"]) == ["figures/pca.png", "report.json"]
    assert done["finished_at"] and done["error"] is None

    link = client.get(f"/api/sessions/{sid}/runs/GSE100001/{CONTRAST}/files/figures/pca.png")
    assert link.status_code == 200
    assert httpx.get(link.json()["url"]).content == b"\x89PNG fake"
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


def test_counts_come_back_from_storage_when_cache_is_wiped(
    client: TestClient,
    tmp_path: Path,
    collected: str,
    wait_runs: Callable[..., list[dict]],  # type: ignore[type-arg]
) -> None:
    """The disk is a cache: a fresh machine pulls the counts from Storage before running."""
    shutil.rmtree(tmp_path / "sessions" / collected)
    r = client.post(f"/api/sessions/{collected}/runs", json=design_for("GSE100001"))
    assert r.status_code == 202
    assert wait_runs(client, collected)[0]["status"] == "complete"


def test_crash_and_timeout_are_recorded(
    client: TestClient,
    collected: str,
    monkeypatch: pytest.MonkeyPatch,
    wait_runs: Callable[..., list[dict]],  # type: ignore[type-arg]
) -> None:
    sid = collected
    monkeypatch.setitem(os.environ, "FAKE_PIPELINE", "crash")
    client.post(f"/api/sessions/{sid}/runs", json=design_for("GSE100001"))
    (failed,) = wait_runs(client, sid)
    assert failed["status"] == "failed" and "exited with code 2" in failed["error"]
    assert failed["report"] is None  # the earlier verdict for this contrast is gone

    monkeypatch.setitem(os.environ, "FAKE_PIPELINE", "hang")
    client.post(f"/api/sessions/{sid}/runs", json=design_for("GSE100001"))
    (killed,) = wait_runs(client, sid)
    assert killed["status"] == "failed" and "killed after" in killed["error"]


def test_restart_resumes_running_runs(
    api: ApiFactory,
    pg: Callable[..., Any],
    wait_collected: Callable[..., list[dict]],  # type: ignore[type-arg]
    wait_runs: Callable[..., list[dict]],  # type: ignore[type-arg]
) -> None:
    """A run row left 'running' by a dead process is re-dispatched by the next one; one
    that has already been retried max_attempts times is failed instead."""
    with api(run_command=FAKE) as c:
        sid = c.post("/api/sessions").json()["id"]
        c.post(f"/api/sessions/{sid}/datasets", json={"gses": ["GSE100001", "GSE100003"]})
        wait_collected(c, sid)
    design = json.dumps(design_for("GSE100001"))
    pg(
        "insert into runs (session_id, gse, status, design, attempts) values "
        "($1, 'GSE100001', 'running', $2::jsonb, 0), ($1, 'GSE100003', 'running', $2::jsonb, 2)",
        sid,
        design,
    )
    pg(
        "insert into run_contrasts (session_id, gse, contrast, status) values "
        "($1, 'GSE100001', $2, 'running'), ($1, 'GSE100003', $2, 'running')",
        sid,
        CONTRAST,
    )
    with api(run_command=FAKE, max_attempts=2) as c:
        resumed, exhausted = wait_runs(c, sid)
    assert resumed["gse"] == "GSE100001" and resumed["status"] == "complete"
    assert exhausted["status"] == "failed" and "restart" in exhausted["error"]
    assert (
        pg("select status from runs where session_id = $1 and gse = 'GSE100003'", sid)[0]["status"]
        == "finished"
    )
