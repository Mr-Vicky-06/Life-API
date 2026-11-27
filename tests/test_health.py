"""Tests for the /health endpoint using FastAPI TestClient and respx."""
from __future__ import annotations

import os

import httpx
import respx
from fastapi.testclient import TestClient

_DB_PORT = os.getenv("DB_PORT", "5432")
os.environ.setdefault("APP_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", f"postgresql+psycopg://life:life@localhost:{_DB_PORT}/life_test")
os.environ.setdefault(
    "DATABASE_URL_RO",
    f"postgresql+psycopg://life_ro:life_ro@localhost:{_DB_PORT}/life_test",
)

from app.config import Settings, get_settings  # noqa: E402
from app.main import app  # noqa: E402


def test_health_endpoint_schema():
    """Asserts that GET /health returns HTTP 200 with required keys and configured router."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "db" in data
    assert "llm" in data
    assert "llm_detail" in data
    assert "router" in data
    assert data["router"] == (get_settings().router_model.strip().lower() or "none")


@respx.mock
def test_health_reports_configured_router(monkeypatch):
    """GET /health reports configured router name ('general', 'needle', or 'none' if empty)."""
    model_tag = get_settings().llm_model.removeprefix("ollama/")
    respx.get("http://127.0.0.1:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": model_tag}]})
    )
    for router_cfg, expected in [("general", "general"), ("needle", "needle"), ("", "none")]:
        monkeypatch.setattr(
            "app.api.routes_health.get_settings",
            lambda r=router_cfg: Settings(
                app_env="dev",
                app_api_key="test-key",
                database_url=f"postgresql+psycopg://life:life@localhost:{_DB_PORT}/life_test",
                database_url_ro=(
                    f"postgresql+psycopg://life_ro:life_ro@localhost:{_DB_PORT}/life_test"
                ),
                router_model=r,
            ),
        )
        data = TestClient(app).get("/health").json()
        assert data["router"] == expected


@respx.mock
def test_health_endpoint_ollama_present():
    """When Ollama is up and the configured model is present, llm should be True."""
    model_tag = get_settings().llm_model.removeprefix("ollama/")
    respx.get("http://127.0.0.1:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": model_tag}]})
    )
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["llm"] is True
    assert data["llm_detail"] is None


@respx.mock
def test_health_endpoint_ollama_model_not_found():
    """When Ollama is up but the model is missing, llm_detail should state 'model not found'."""
    respx.get("http://127.0.0.1:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "mistral:latest"}]})
    )
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["llm"] is False
    assert data["llm_detail"] is not None
    assert "model not found" in data["llm_detail"].lower()


@respx.mock
def test_health_endpoint_ollama_connection_refused():
    """When Ollama is not running, llm_detail should state 'connection refused'."""
    msg = "[WinError 10061] No connection could be made because target actively refused it"
    respx.get("http://127.0.0.1:11434/api/tags").mock(
        side_effect=httpx.ConnectError(msg)
    )
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["llm"] is False
    assert data["llm_detail"] is not None
    assert "connection refused" in data["llm_detail"].lower()


@respx.mock
def test_health_endpoint_ollama_timed_out():
    """When Ollama connection times out, llm_detail should state 'timed out'."""
    respx.get("http://127.0.0.1:11434/api/tags").mock(
        side_effect=httpx.TimeoutException("Connection timed out")
    )
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["llm"] is False
    assert data["llm_detail"] is not None
    assert "timed out" in data["llm_detail"].lower()
