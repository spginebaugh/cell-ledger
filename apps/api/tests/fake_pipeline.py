"""Stand-in for ``python -m cell_ledger.cli`` in API tests.

Writes a minimal but valid report.json per contrast into <out-root>/<GSE>/<contrast>/,
plus a figure, the way the real pipeline lays things out. FAKE_PIPELINE=crash exits 2
without writing anything; FAKE_PIPELINE=hang sleeps until killed.
"""

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from cell_ledger.report.models import AnalysisReport
from cell_ledger.samplesheet import Contrast


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("cmd")
    p.add_argument("gse")
    p.add_argument("--design", required=True)
    p.add_argument("--counts", required=True)
    p.add_argument("--annotation", required=True)
    p.add_argument("--out-root", required=True)
    p.add_argument("--genes")
    p.add_argument("--n-cpus")
    p.add_argument("--no-enrichment", action="store_true")
    p.add_argument("--no-figures", action="store_true")
    a = p.parse_args()
    print("fake pipeline", a.gse, a.counts, a.annotation, flush=True)
    mode = os.environ.get("FAKE_PIPELINE", "ok")
    if mode == "crash":
        print("boom", file=sys.stderr)
        return 2
    if mode == "hang":
        time.sleep(60)
    assert Path(a.counts).exists() and Path(a.annotation).exists()
    design = json.loads(Path(a.design).read_text())
    for c in design["contrasts"]:
        contrast = Contrast.model_validate(c)
        out = Path(a.out_root) / a.gse / contrast.name
        (out / "figures").mkdir(parents=True)
        (out / "figures" / "pca.png").write_bytes(b"\x89PNG fake")
        report = AnalysisReport(
            gse=a.gse,
            contrast=contrast,
            status="complete",
            created_at=datetime.now(UTC),
            versions={"fake": "1"},
            params={"genes": a.genes},
        )
        (out / "report.json").write_text(report.model_dump_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
