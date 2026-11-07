import json
import subprocess

import pytest

from evals import run


@pytest.mark.parametrize("mode", ["stable", "changed", "missing_report"])
def test_report_records_sources_and_rejects_stale_or_changing_results(tmp_path, monkeypatch, mode):
    source = tmp_path / "evals/example.py"
    source.parent.mkdir()
    source.write_text("before\n")
    private = tmp_path / "evals/private/secret.json"
    private.parent.mkdir()
    private.write_text('"private"')
    output = tmp_path / "data/evals"
    output.mkdir(parents=True)
    (output / "integrity.xml").write_text('<testsuites><testsuite tests="999"/></testsuites>')
    monkeypatch.setattr(run, "git_state", lambda root: {"code_revision": "abc", "dirty": True})

    def execute(command, **kwargs):
        assert not (output / "integrity.xml").exists()
        if mode != "missing_report":
            (output / "integrity.xml").write_text(
                '<testsuites><testsuite tests="1" failures="0" '
                'errors="0" skipped="0"/></testsuites>'
            )
        if mode == "changed":
            source.write_text("after\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(run.subprocess, "run", execute)
    assert run.run_integrity(tmp_path) == (0 if mode == "stable" else 1)
    report = json.loads((output / "integrity.json").read_text())
    assert report["code_revision"] == "abc" and report["dirty"]
    assert report["test_scope"] == run.TEST_SCOPE
    assert report["command"][1:3] == ["-m", "pytest"]
    assert set(report["source_sha256_before"]) == {"evals/example.py"}
    assert report["provenance_stable"] == (mode == "stable")
    assert report["changed_source_files"] == (["evals/example.py"] if mode == "changed" else [])
    assert report["counts"] == (
        None
        if mode == "missing_report"
        else {
            "tests": 1,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
        }
    )
