from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CELL_LEDGER_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    cors_origins: list[str] = ["http://localhost:5173"]

    # NCBI E-utilities: 10 requests/s with a key, 3 without.
    ncbi_api_key: SecretStr | None = None

    # Supabase Storage for session files. Unset -> files stay on local disk only.
    supabase_url: str | None = None
    supabase_secret_key: SecretStr | None = None
    supabase_bucket: str = "sessions"

    # Sessions are ephemeral: local copies older than this are swept at startup.
    session_ttl_hours: float = 24
    max_datasets_per_request: int = 10
    max_concurrent_downloads: int = 3


settings = Settings()
