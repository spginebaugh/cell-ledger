"""Comparison endpoints: the fake pipeline produces the member runs, the real
``cell-ledger run-set --compare-only`` compares them (without DE tables the result is
``insufficient``, which is the honest answer and still exercises the whole path)."""

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from .conftest import ApiFactory
from .test_runs import CONTRAST, FAKE, design_for


@pytest.fixture
def client(api: ApiFactory) -> Iterator[TestClient]:
    with api(run_command=FAKE, run_timeout_minutes=0.2, max_datasets_per_request=3) as c:
        yield c


def _wait_comparison(client: TestClient, sid: str, name: str, timeout: float = 120) -> dict:  # type: ignore[type-arg]
    import time

    deadline = time.monotonic() + timeout
    while True:
        view = client.get(f"/api/sessions/{sid}/comparisons/{name}").json()
        if view["status"] != "running":
            return view
        assert time.monotonic() < deadline, view
        time.sleep(0.2)


def test_compare_two_runs(
    client: TestClient,
    tmp_path: Path,
    wait_collected: Callable[..., list[dict]],  # type: ignore[type-arg]
    wait_runs: Callable[..., list[dict]],  # type: ignore[type-arg]
) -> None:
    sid = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{sid}/datasets", json={"gses": ["GSE100001", "GSE100003"]})
    wait_collected(client, sid)
    # GSE100003 has counts but no SOFT -> failed; only GSE100001 can run. Run it twice under
    # two contrast names so the comparison has two members.
    body = {
        "name": "pilot",
        "question": "does anything replicate?",
        "case_label": "case",
        "control_label": "control",
        "members": [
            {"gse": "GSE100001", "contrast": CONTRAST},
            {"gse": "GSE100001", "contrast": "second"},
        ],
        "genes_of_interest": ["CXCL9"],
    }
    # Members that have no run yet are refused.
    r = client.post(f"/api/sessions/{sid}/comparisons", json=body)
    assert r.status_code == 409 and "no run" in r.json()["detail"]

    design = design_for("GSE100001")
    second = json.loads(json.dumps(design["contrasts"][0]))
    second["name"] = "second"
    design["contrasts"].append(second)
    assert client.post(f"/api/sessions/{sid}/runs", json=design).status_code == 202
    runs = wait_runs(client, sid)
    assert [r["status"] for r in runs] == ["complete", "complete"]

    r = client.post(f"/api/sessions/{sid}/comparisons", json=body)
    assert r.status_code == 202
    started = r.json()
    assert started["status"] == "running" and started["request"]["name"] == "pilot"
    assert client.post(f"/api/sessions/{sid}/comparisons", json=body).status_code == 409

    view = _wait_comparison(client, sid, "pilot")
    assert view["status"] == "insufficient", view["error"]
    rep = view["report"]
    assert rep["name"] == "pilot" and rep["question"] == body["question"]
    # Both members were found but neither has a DE table, so neither could be pooled.
    assert {e["reason"] for e in rep["excluded"]} == {"no_de_table"}
    assert view["uploaded"] and "comparison.json" in view["files"]
    assert set(view["urls"]) == set(view["files"]) and view["urls_expire_in"] == 24 * 3600
    assert json.loads(httpx.get(view["urls"]["comparison.json"]).content)["name"] == "pilot"
    listed = client.get(f"/api/sessions/{sid}/comparisons").json()
    assert [c["name"] for c in listed] == ["pilot"]
    assert client.get(f"/api/sessions/{sid}/comparisons/nope").status_code == 404
    link = client.get(f"/api/sessions/{sid}/comparisons/pilot/files/comparison.md")
    assert link.status_code == 200
    log = (tmp_path / "sessions" / sid / "comparisons" / "pilot.log").read_text()
    assert "pilot" in log


def test_failed_retry_does_not_reuse_earlier_report(
    api: ApiFactory,
    tmp_path: Path,
    wait_collected: Callable[..., list[dict]],  # type: ignore[type-arg]
    wait_runs: Callable[..., list[dict]],  # type: ignore[type-arg]
) -> None:
    """The first attempt leaves comparison.json behind (``insufficient``). When the retry's
    process fails, that is the result; the stale file must not stand in for it."""
    body = {
        "name": "retry",
        "question": "does anything replicate?",
        "case_label": "case",
        "control_label": "control",
        "members": [
            {"gse": "GSE100001", "contrast": CONTRAST},
            {"gse": "GSE100001", "contrast": "second"},
        ],
        "genes_of_interest": ["CXCL9"],
    }
    with api(run_command=FAKE, run_timeout_minutes=0.2) as client:
        sid = client.post("/api/sessions").json()["id"]
        client.post(f"/api/sessions/{sid}/datasets", json={"gses": ["GSE100001"]})
        wait_collected(client, sid)
        design = design_for("GSE100001")
        second = json.loads(json.dumps(design["contrasts"][0]))
        second["name"] = "second"
        design["contrasts"].append(second)
        assert client.post(f"/api/sessions/{sid}/runs", json=design).status_code == 202
        assert [r["status"] for r in wait_runs(client, sid)] == ["complete", "complete"]
        assert client.post(f"/api/sessions/{sid}/comparisons", json=body).status_code == 202
        assert _wait_comparison(client, sid, "retry")["status"] == "insufficient"
    stale = tmp_path / "sessions" / sid / "comparisons" / "retry" / "comparison.json"
    assert stale.exists()

    with api(run_command=FAKE, compare_command=("sh", "-c", "exit 3")) as client:
        assert client.post(f"/api/sessions/{sid}/comparisons", json=body).status_code == 202
        view = _wait_comparison(client, sid, "retry")
    assert view["status"] == "failed"
    assert view["error"] and "exited with code 3" in view["error"]
    assert view["report"] is None
    assert not stale.exists()
