from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CELL_LEDGER_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")

    # Built frontend (apps/web/dist). Set -> served from "/" on the same origin as the
    # API, which is how the container runs. Unset -> API only (Vite dev server owns the UI).
    web_dist: Path | None = None

    # Only needed when the UI is served from another origin (the Vite dev server).
    cors_origins: list[str] = ["http://localhost:5173"]

    # NCBI E-utilities: 10 requests/s with a key, 3 without.
    ncbi_api_key: SecretStr | None = None

    # Supabase Storage for session files. Unset -> files stay on local disk only.
    supabase_url: str | None = None
    supabase_secret_key: SecretStr | None = None
    supabase_bucket: str = "sessions"

    # Claude drives the clarifying/narrowing loop. Opus 5.5 defaults to medium effort.
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "medium"

    # Exa semantic search over GEO pages; every hit is re-verified against GEO.
    exa_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("CELL_LEDGER_EXA_API_KEY", "EXA_API_KEY")
    )

    # Sessions are ephemeral: local copies older than this are swept at startup.
    session_ttl_hours: float = 24
    max_datasets_per_request: int = 10
    max_concurrent_downloads: int = 3

    # Pipeline runs are `cell-ledger run` subprocesses. Each pydeseq2 fit wants a few GB, so
    # the cap is per machine memory: 2 on 8 GB, 4 on 16 GB. n_cpus unset -> pipeline default.
    max_concurrent_runs: int = 2
    run_n_cpus: int | None = None
    run_timeout_minutes: float = 30


settings = Settings()
