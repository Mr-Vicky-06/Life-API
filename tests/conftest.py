"""Shared pytest fixtures — populated progressively across phases."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _set_env():
    """Ensure minimum env vars are present for all tests."""
    os.environ.setdefault("APP_API_KEY", "test-key")
    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://life:life@localhost:5432/life_test")
    os.environ.setdefault(
        "DATABASE_URL_RO",
        "postgresql+psycopg://life_ro:life_ro@localhost:5432/life_test",
    )


@pytest.fixture(scope="module")
def api_client():
    from app.main import app
    return TestClient(app)
