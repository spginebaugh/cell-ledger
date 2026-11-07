"""Dump the OpenAPI schema to a file: ``python -m cell_ledger_api.openapi out.json``."""

import json
import sys
from pathlib import Path

from cell_ledger_api.main import app

if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    out.write_text(json.dumps(app.openapi(), indent=2) + "\n")
    print(f"wrote {out}")
