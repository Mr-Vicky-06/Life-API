"""Application configuration via pydantic-settings.

All values come from environment variables / .env file.
Never import this module from tests directly — use the fixture in conftest.py.
"""
from __future__ import annotations

import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_API_KEY = "change-me"


def validate_startup_security(settings: Settings) -> None:
    """Refuse non-dev execution when APP_API_KEY is still the default or empty."""
    if settings.app_env.lower() != "dev" and settings.app_api_key.strip() in ("", DEFAULT_API_KEY):
        raise ValueError(
            "Refusing to start: APP_API_KEY must be changed from the default "
            "when APP_ENV is not 'dev'."
        )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "dev"
    app_api_key: str = Field(..., description="API key for X-API-Key auth")
    app_timezone: str = "Asia/Kolkata"
    seed_end_date: datetime.date = datetime.date(2026, 11, 23)
    reference_date: datetime.date | None = None

    @field_validator("reference_date", mode="before")
    @classmethod
    def _empty_reference_date_to_none(cls, value: Any) -> Any:
        if value == "" or (isinstance(value, str) and not value.strip()):
            return None
        return value

    database_url: str = Field(..., description="Read-write Postgres DSN")
    database_url_ro: str = Field(..., description="Read-only Postgres DSN")

    llm_model: str = "ollama/qwen2.5-coder:7b"
    llm_fallback_model: str = ""
    llm_api_base: str = "http://127.0.0.1:11434"
    llm_num_ctx: int = 4096
    llm_keep_alive: str = "30m"
    cloud_llm_enabled: bool = False
    router_model: str = "general"

    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    github_token: str = ""
    github_username: str = ""
    health_id_regex: str = ""

    @model_validator(mode="after")
    def _check_non_dev_api_key(self) -> Settings:
        validate_startup_security(self)
        return self


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return cached settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
