"""Shared pytest fixtures — populated progressively across phases."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _set_env():
    """Ensure minimum env vars are present for all tests."""
    db_port = os.getenv("DB_PORT", "5432")
    os.environ.setdefault("APP_API_KEY", "test-key")
    os.environ.setdefault(
        "DATABASE_URL", f"postgresql+psycopg://life:life@127.0.0.1:{db_port}/life_test"
    )
    os.environ.setdefault(
        "DATABASE_URL_RO",
        f"postgresql+psycopg://life_ro:life_ro@127.0.0.1:{db_port}/life_test",
    )


@pytest.fixture(scope="module")
def api_client():
    from app.main import app
    return TestClient(app)
