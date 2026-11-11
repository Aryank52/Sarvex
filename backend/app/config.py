"""Central typed configuration.

Every runtime dependency (database, storage, connectors, models) is configured
here or in ``config/models.yaml``. No credentials are hard-coded.
"""
from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


def _code_version() -> str:
    """Best-effort immutable code identifier for provenance records."""
    env = os.getenv("CODE_VERSION")
    if env:
        return env
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:  # noqa: BLE001 - provenance must never crash startup
        pass
    return "unknown"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_name: str = "SARVEX"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    demo_mode: Literal["auto", "on", "off"] = "auto"
    run_inline_worker: bool = True
    offline_mode: bool = False

    # Storage
    database_url: str = ""
    redis_url: str | None = None
    object_storage_backend: Literal["local", "s3"] = "local"
    object_storage_dir: Path = BACKEND_DIR / "data" / "objects"
    object_storage_endpoint: str | None = None
    object_storage_access_key: str | None = None
    object_storage_secret_key: str | None = None
    object_storage_bucket: str = "sarvex"
    object_storage_region: str = "us-east-1"

    # Connectors
    nasa_earthdata_username: str | None = None
    nasa_earthdata_password: str | None = None
    nasa_earthdata_token: str | None = None
    asf_search_url: str = "https://api.daac.asf.alaska.edu/services/search/param"
    bhoonidhi_base_url: str = "https://bhoonidhi.nrsc.gov.in"
    # Full search endpoint supplied by the operator. SARVEX does not assume an
    # undocumented Bhoonidhi API shape; without this URL the connector is
    # reported as unconfigured rather than returning fabricated results.
    bhoonidhi_search_url: str | None = None
    bhoonidhi_api_key: str | None = None
    stac_search_urls: str = ""
    local_ingest_dirs: str = str(BACKEND_DIR / "data" / "local") + "," + str(BACKEND_DIR / "data" / "uploads")

    # Models
    models_config_path: str = "config/models.yaml"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    reranker_api_key: str | None = None
    reranker_base_url: str | None = None
    embedding_dimension: int = 384

    # Security / observability
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    max_upload_mb: int = 512
    rate_limit_per_minute: int = 240
    log_level: str = "INFO"
    structured_logs: bool = True
    code_version: str = Field(default_factory=_code_version)

    @property
    def resolved_database_url(self) -> str:
        """Return an explicit database URL or the SQLite development fallback."""
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(BACKEND_DIR / 'data' / 'sarvex.db').as_posix()}"

    @property
    def using_sqlite(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def stac_url_list(self) -> list[str]:
        return [u.strip() for u in self.stac_search_urls.split(",") if u.strip()]

    @property
    def local_ingest_paths(self) -> list[Path]:
        return [Path(p.strip()) for p in self.local_ingest_dirs.split(",") if p.strip()]

    @property
    def models_config_file(self) -> Path:
        p = Path(self.models_config_path)
        return p if p.is_absolute() else (BACKEND_DIR / p)

    @field_validator("database_url", "redis_url", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return ""
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
