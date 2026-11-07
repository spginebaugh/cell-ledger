"""Dump the OpenAPI schema to a file: ``python -m cell_ledger_api.openapi out.json``.

Builds the app with placeholder settings: the schema needs routes and models, not a
database, so this works without a Supabase stack or a .env.
"""

import json
import sys
from pathlib import Path

from cell_ledger_api.main import create_app
from cell_ledger_api.settings import Settings

if __name__ == "__main__":
    cfg = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql://placeholder",
        supabase_url="http://placeholder",
        supabase_secret_key="placeholder",
    )
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    out.write_text(json.dumps(create_app(cfg).openapi(), indent=2) + "\n")
    print(f"wrote {out}")
