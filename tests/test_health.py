"""Tests for the /health endpoint using FastAPI TestClient and respx."""
from __future__ import annotations

import os

import httpx
import respx
from fastapi.testclient import TestClient

os.environ.setdefault("APP_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://life:life@localhost:5432/life_test")
os.environ.setdefault(
    "DATABASE_URL_RO",
    "postgresql+psycopg://life_ro:life_ro@localhost:5432/life_test",
)

from app.main import app  # noqa: E402


def test_health_endpoint_schema():
    """Asserts that GET /health returns HTTP 200 with the required keys."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "db" in data
    assert "llm" in data
    assert "llm_detail" in data
    assert "router" in data
    assert data["router"] in ("needle", "none")


@respx.mock
def test_health_endpoint_ollama_present():
    """When Ollama is up and the configured model is present, llm should be True."""
    respx.get("http://127.0.0.1:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})
    )
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["llm"] is True
    assert data["llm_detail"] is None


@respx.mock
def test_health_endpoint_ollama_model_missing():
    """When Ollama is up but the model is missing, llm should be False with details."""
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
    assert "not found" in data["llm_detail"]


@respx.mock
def test_health_endpoint_ollama_down():
    """When Ollama is unreachable, llm should be False with short reason and no secrets."""
    respx.get("http://127.0.0.1:11434/api/tags").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["llm"] is False
    assert data["llm_detail"] is not None
    assert "unavailable" in data["llm_detail"]
