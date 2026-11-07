"""Run engineering checks with source provenance; not a biological benchmark."""

import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

TEST_SCOPE = ["packages/core/tests", "apps/api/tests", "evals/tests"]
SOURCE_SCOPE = ["packages/core", "apps/api", "evals"]


def source_fingerprints(root: Path) -> dict[str, str]:
    """Hash public source, test fixtures and configuration, never local secrets/outputs."""
    paths = [root / name for name in ("pyproject.toml", "uv.lock")]
    for scope in SOURCE_SCOPE:
        paths.extend(
            path
            for path in (root / scope).rglob("*")
            if path.suffix in {".py", ".json", ".toml", ".tsv", ".csv", ".gmt"}
            and not {"private", "__pycache__", ".pytest_cache", ".ruff_cache"}
            & set(path.relative_to(root).parts)
        )
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(set(paths))
        if path.is_file() and not path.is_symlink()
    }


def git_state(root: Path) -> dict:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    return {
        "code_revision": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain", "--untracked-files=all")),
    }


def run_integrity(root: Path) -> int:
    output = root / "data/evals"
    output.mkdir(parents=True, exist_ok=True)
    xml_file = output / "integrity.xml"
    # Never accidentally summarize a previous run after pytest fails to produce XML.
    xml_file.unlink(missing_ok=True)
    command = [sys.executable, "-m", "pytest", *TEST_SCOPE, f"--junitxml={xml_file}"]
    before = source_fingerprints(root)
    before_git = git_state(root)
    started = datetime.now(UTC).isoformat()
    result = subprocess.run(command, cwd=root, check=False)
    after = source_fingerprints(root)
    after_git = git_state(root)
    changed = sorted(
        name for name in before.keys() | after.keys() if before.get(name) != after.get(name)
    )
    counts = None
    report_error = None
    try:
        suites = ET.parse(xml_file).getroot().findall("testsuite")
        if not suites:
            raise ValueError("No test suites in pytest report")
        counts = {
            key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
            for key in ("tests", "failures", "errors", "skipped")
        }
    except (OSError, ET.ParseError, ValueError) as exc:
        report_error = f"Could not read this run's pytest report: {exc}"
    valid = not changed and before_git == after_git and report_error is None
    report = {
        "kind": "engineering_integrity",
        "started_at": started,
        "timestamp": datetime.now(UTC).isoformat(),
        **before_git,
        "git_state_after": after_git,
        "command": command,
        "test_scope": TEST_SCOPE,
        "source_sha256_before": before,
        "source_sha256_after": after,
        "changed_source_files": changed,
        "provenance_stable": valid,
        "pytest_exit_code": result.returncode,
        "counts": counts,
        "report_error": report_error,
        "biological_benchmark": "not_run",
        "baseline_comparison": "not_run",
    }
    (output / "integrity.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps({k: v for k, v in report.items() if not k.startswith("source_sha256")}, indent=2)
    )
    return result.returncode or (0 if valid else 1)


if __name__ == "__main__":
    raise SystemExit(run_integrity(Path(__file__).resolve().parents[1]))
