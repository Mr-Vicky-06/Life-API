"""Application configuration via pydantic-settings.

All values come from environment variables / .env file.
Never import this module from tests directly — use the fixture in conftest.py.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    database_url: str = Field(..., description="Read-write Postgres DSN")
    database_url_ro: str = Field(..., description="Read-only Postgres DSN")

    llm_model: str = "ollama/llama3.1:8b"
    llm_fallback_model: str = ""
    llm_api_base: str = "http://127.0.0.1:11434"
    cloud_llm_enabled: bool = False
    router_model: str = "general"

    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    github_token: str = ""
    github_username: str = ""
    health_id_regex: str = ""


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return cached settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
