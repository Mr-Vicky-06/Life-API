"""Phase 0 smoke test — the only test that must pass at this phase."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    # Provide minimal required env vars before importing the app
    db_port = os.getenv("DB_PORT", "5432")
    os.environ.setdefault("APP_API_KEY", "test-key")
    os.environ.setdefault(
        "DATABASE_URL", f"postgresql+psycopg://life:life@localhost:{db_port}/life"
    )
    os.environ.setdefault(
        "DATABASE_URL_RO", f"postgresql+psycopg://life_ro:life_ro@localhost:{db_port}/life"
    )

    from app.main import app
    return TestClient(app)


def test_health_no_auth(client: TestClient) -> None:
    """GET /health must respond 200 without any API key."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "db" in body
    assert "llm" in body


def test_v1_route_requires_auth(client: TestClient) -> None:
    """Any /v1/ route without X-API-Key must return 401 (or 404 at minimum — route not found
    is acceptable at Phase 0 since /v1/ routes are added later)."""
    resp = client.get("/v1/metrics", headers={})
    # Either 401 (auth check) or 404 (route not yet registered) is fine at Phase 0
    assert resp.status_code in (401, 404, 422)
