"""Dashboard configuration loaded via pydantic-settings (API_URL and APP_API_KEY)."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DashboardConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    api_url: str = Field(default="http://127.0.0.1:8000", description="Life-API base URL")
    app_api_key: str = Field(default="", description="API key sent as X-API-Key header")


def get_dashboard_config() -> DashboardConfig:
    """Return current DashboardConfig reading environment and .env."""
    return DashboardConfig()
