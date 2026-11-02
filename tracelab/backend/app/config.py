from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All settings come from TRACELAB_* environment variables (or a .env file)."""

    model_config = SettingsConfigDict(env_prefix="TRACELAB_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./tracelab.db"
    # When set, every /api request (except /api/health) must send X-API-Key.
    api_key: str | None = None
    # Outbound requests to private/loopback/link-local addresses are blocked unless this is true.
    allow_private_targets: bool = False

    # Run worker threads inside the API process (handy for single-container deploys).
    embedded_worker: bool = False
    worker_concurrency: int = 4
    poll_interval_s: float = 0.5
    # A "running" request whose lock is older than this is assumed to belong to a dead worker.
    lease_seconds: int = 60

    max_body_bytes: int = 256 * 1024
    response_capture_bytes: int = 8 * 1024

    log_level: str = "INFO"
    cors_origins: str = ""  # comma separated; empty disables CORS


@lru_cache
def get_settings() -> Settings:
    return Settings()
