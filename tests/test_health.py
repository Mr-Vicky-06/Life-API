"""Tests for the /health endpoint using FastAPI TestClient."""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

os.environ.setdefault("APP_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://life:life@localhost:5432/life_test")
os.environ.setdefault(
    "DATABASE_URL_RO",
    "postgresql+psycopg://life_ro:life_ro@localhost:5432/life_test",
)

from app.main import app  # noqa: E402


def test_health_endpoint_returns_200():
    """Asserts that GET /health returns HTTP 200 with ok status and db/llm keys."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "db" in data
    assert "llm" in data
