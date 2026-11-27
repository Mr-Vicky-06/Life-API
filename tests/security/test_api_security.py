"""API security conformance tests (SECURITY.md §6: CORS, rate limit, constant-time auth)."""
from __future__ import annotations

import hmac
import inspect
import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

_DB_PORT = os.getenv("DB_PORT", "5432")
os.environ.setdefault("APP_API_KEY", "api-security-test-key-1234567890")
os.environ.setdefault("DATABASE_URL", f"postgresql+psycopg://life:life@127.0.0.1:{_DB_PORT}/life_test")
os.environ.setdefault(
    "DATABASE_URL_RO",
    f"postgresql+psycopg://life_ro:life_ro@127.0.0.1:{_DB_PORT}/life_test",
)

from app.deps import verify_api_key  # noqa: E402
from app.main import RATE_LIMIT, _rate_store, app  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limit_store() -> Generator[None, None, None]:
    _rate_store.clear()
    yield
    _rate_store.clear()


def test_verify_api_key_uses_hmac_compare_digest() -> None:
    """Confirm verify_api_key source enforces constant-time hmac.compare_digest."""
    src = inspect.getsource(verify_api_key)
    assert "hmac.compare_digest" in src or hmac.compare_digest.__name__ in src


def test_cors_allows_dashboard_origin_only() -> None:
    """Only http://localhost:8501 is echoed in Access-Control-Allow-Origin."""
    client = TestClient(app)

    allowed = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:8501",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:8501"

    disallowed = client.options(
        "/health",
        headers={
            "Origin": "https://untrusted.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in disallowed.headers


def test_v1_missing_or_invalid_api_key_returns_401_envelope() -> None:
    """Requests without valid X-API-Key return HTTP 401 with standard error envelope."""
    client = TestClient(app)
    for hdrs in ({}, {"X-API-Key": "wrong-key"}):
        resp = client.get("/v1/metrics?from=2026-11-01&to=2026-11-05", headers=hdrs)
        assert resp.status_code == 401
        body = resp.json()
        assert body["error"]["code"] == "unauthorized"


def test_v1_rate_limit_enforces_60_req_per_min_per_key() -> None:
    """Rate limiter allows 60 requests/min per key and rejects request 61 with HTTP 429."""
    client = TestClient(app)
    headers = {"X-API-Key": "rate-limit-probe-key"}

    for _ in range(RATE_LIMIT):
        resp = client.get("/v1/metrics?from=2026-11-01&to=2026-11-05", headers=headers)
        assert resp.status_code != 429

    limited = client.get("/v1/metrics?from=2026-11-01&to=2026-11-05", headers=headers)
    assert limited.status_code == 429
    body = limited.json()
    assert body["error"]["code"] == "rate_limited"
