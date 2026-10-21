"""Application settings loaded from environment variables and an optional ``.env``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    All variables use the ``BAMBOO11Y_`` prefix. Values in ``.env`` are convenient for
    local use; real deployments should inject configuration through their platform's
    secret/config mechanism.
    """

    model_config = SettingsConfigDict(
        env_prefix="BAMBOO11Y_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Bamboo11y"
    environment: str = "local"
    database_url: str = "sqlite:///./data/bamboo11y.db"
    database_echo: bool = False
    service_catalog_path: Path = Path("config/services.yaml")
    static_dir: Path = Path("frontend/dist")

    correlation_window_minutes: int = Field(default=15, ge=1, le=1440)
    topology_correlation_enabled: bool = True
    topology_window_minutes: int = Field(default=10, ge=1, le=1440)
    change_context_window_minutes: int = Field(default=120, ge=1, le=10080)
    future_skew_tolerance_seconds: int = Field(default=300, ge=0, le=86400)

    rate_limit_per_minute: int = Field(default=120, ge=0, le=100000)
    max_payload_bytes: int = Field(default=1_000_000, ge=1024, le=10_000_000)
    max_alerts_per_request: int = Field(default=100, ge=1, le=1000)

    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    log_level: str = "INFO"
    log_json: bool = True

    notification_webhook_url: str | None = None
    notification_timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("log level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        return normalized

    @field_validator("notification_webhook_url")
    @classmethod
    def validate_notification_url(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        normalized = value.strip()
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("notification webhook URL must start with http:// or https://")
        # The URL is operator-controlled, not user-controlled. Never accept credentials in
        # the URL because it would be stored and could leak through logs/config dumps.
        if "@" in normalized.split("://", 1)[1].split("/", 1)[0]:
            raise ValueError("notification webhook URL must not embed credentials")
        return normalized

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
