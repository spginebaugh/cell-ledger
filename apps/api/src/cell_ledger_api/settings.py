from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Local and Fly run the same image with the same variables.

    Postgres and Supabase Storage are required: the database is the only record of sessions,
    datasets and runs, and Storage is the only durable copy of their files. Starting without
    either is a configuration error, not a degraded mode.
    """

    model_config = SettingsConfigDict(env_prefix="CELL_LEDGER_", env_file=".env", extra="ignore")

    # Postgres connection string (the Supabase project's; local stack:
    # postgresql://postgres:postgres@127.0.0.1:57322/postgres).
    database_url: SecretStr

    # Supabase Storage: project URL, secret key (sb_secret_... / service_role) and bucket.
    supabase_url: str
    supabase_secret_key: SecretStr
    supabase_bucket: str = "sessions"

    # Local cache of GEO downloads and run outputs. Nothing here is the source of truth; it
    # can be wiped and will be refilled from Storage or NCBI as needed.
    data_dir: Path = Path("data")

    # Built frontend (apps/web/dist). Set -> served from "/" on the same origin as the
    # API, which is how the container runs. Unset -> API only (Vite dev server owns the UI).
    web_dist: Path | None = None

    # Only needed when the UI is served from another origin (the Vite dev server).
    cors_origins: list[str] = ["http://localhost:5173"]

    # NCBI E-utilities: 10 requests/s with a key, 3 without.
    ncbi_api_key: SecretStr | None = None

    # Claude drives the clarifying/narrowing loop. Opus 5.5 defaults to medium effort.
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "medium"
    # The design step (label samples, choose the contrast) can run on a faster model than
    # discovery. Unset -> the same model and effort as discovery.
    design_model: str | None = None
    design_effort: str | None = None

    # Exa semantic search over GEO pages; every hit is re-verified against GEO.
    exa_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("CELL_LEDGER_EXA_API_KEY", "EXA_API_KEY")
    )

    # Sessions are ephemeral: rows, files and local copies older than this are deleted by
    # the sweep, which runs at startup and then every sweep_interval_minutes.
    session_ttl_hours: float = 24
    sweep_interval_minutes: float = 60
    max_datasets_per_request: int = 10
    max_concurrent_downloads: int = 3

    # Pipeline runs are `cell-ledger run` subprocesses. Each pydeseq2 fit wants a few GB, so
    # the cap is per machine memory: 2 on 8 GB, 4 on 16 GB. n_cpus unset -> pipeline default.
    max_concurrent_runs: int = 2
    run_n_cpus: int | None = None
    run_timeout_minutes: float = 30
    # Comparisons are lighter (no counts, no fit) but pooled GSEA still takes a while.
    compare_timeout_minutes: float = 15

    # Work interrupted by a restart is re-dispatched at boot, this many times at most, so a
    # job that crashes the machine cannot restart it forever.
    max_attempts: int = 2
