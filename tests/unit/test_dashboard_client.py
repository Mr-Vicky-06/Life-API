"""Unit tests for the HTTP API client in dashboard/api_client.py using respx."""
from __future__ import annotations

import datetime
import json

import httpx
import pytest
import respx

from dashboard.api_client import (
    AGENT_TIMEOUT_S,
    DATA_TIMEOUT_S,
    START_API_HINT,
    DashboardAPIError,
    LifeAPIClient,
)

API_BASE = "http://127.0.0.1:8000"
FAKE_KEY = "unit-test-secret-api-key-999"


@respx.mock
def test_client_sends_api_key_header_and_parses_endpoints() -> None:
    metrics_route = respx.get(f"{API_BASE}/v1/metrics").mock(
        return_value=httpx.Response(
            200,
            json={"from_date": "2026-11-01", "to_date": "2026-11-07", "rows": []},
        )
    )
    screen_route = respx.get(f"{API_BASE}/v1/screen-time").mock(
        return_value=httpx.Response(200, json=[{"category": "dev", "minutes": 120}])
    )
    insight_route = respx.get(f"{API_BASE}/v1/insights/daily").mock(
        return_value=httpx.Response(
            200,
            json={
                "timestamp": "2026-11-07",
                "summary": "Good day.",
                "metrics": {"sleep_hours": 7.5},
                "insights": "Balanced.",
            },
        )
    )
    search_route = respx.post(f"{API_BASE}/v1/search").mock(
        return_value=httpx.Response(200, json=[])
    )
    chat_route = respx.post(f"{API_BASE}/v1/agent/chat").mock(
        return_value=httpx.Response(
            200,
            json={"answer": "42", "steps": [], "model": "stub", "session_id": "s1"},
        )
    )

    client = LifeAPIClient(api_url=API_BASE, api_key=FAKE_KEY)
    assert client.get_metrics(datetime.date(2026, 11, 1), datetime.date(2026, 11, 7))["rows"] == []
    assert client.get_screen_time(datetime.date(2026, 11, 1), datetime.date(2026, 11, 7)) == [
        {"category": "dev", "minutes": 120}
    ]
    assert client.get_daily_insight(datetime.date(2026, 11, 7))["summary"] == "Good day."
    assert client.search_notes("sleep", source_type="journal") == []
    assert client.post_agent_chat("hello", session_id="s1")["answer"] == "42"

    for route in (metrics_route, screen_route, insight_route, search_route, chat_route):
        assert route.called
        req = route.calls[0].request
        assert req.headers["X-API-Key"] == FAKE_KEY
        timeout_ext = req.extensions["timeout"]
        expected_t = AGENT_TIMEOUT_S if route is chat_route else DATA_TIMEOUT_S
        assert timeout_ext["read"] == expected_t

    search_body = json.loads(search_route.calls[0].request.content.decode())
    assert search_body == {"query": "sleep", "top_k": 8, "source_type": "journal"}


@respx.mock
def test_client_maps_401_422_503_and_scrubs_api_key() -> None:
    respx.get(f"{API_BASE}/v1/metrics").mock(
        return_value=httpx.Response(
            401,
            json={"error": {"code": "unauthorized", "message": f"Bad key {FAKE_KEY}"}},
        )
    )
    client = LifeAPIClient(api_url=API_BASE, api_key=FAKE_KEY)
    with pytest.raises(DashboardAPIError) as exc_401:
        client.get_metrics(datetime.date(2026, 11, 1), datetime.date(2026, 11, 7))
    assert exc_401.value.status_code == 401
    assert "API key rejected, check APP_API_KEY in .env" in exc_401.value.message
    assert FAKE_KEY not in str(exc_401.value)

    respx.get(f"{API_BASE}/v1/screen-time").mock(
        return_value=httpx.Response(
            422,
            json={"error": {"code": "validation_error", "message": f"Invalid {FAKE_KEY} range"}},
        )
    )
    with pytest.raises(DashboardAPIError) as exc_422:
        client.get_screen_time(datetime.date(2026, 11, 7), datetime.date(2026, 11, 1))
    assert exc_422.value.status_code == 422
    assert FAKE_KEY not in str(exc_422.value)

    respx.get(f"{API_BASE}/v1/insights/daily").mock(
        return_value=httpx.Response(503, text="Traceback (most recent call last):\nsecret")
    )
    with pytest.raises(DashboardAPIError) as exc_503:
        client.get_daily_insight(datetime.date(2026, 11, 7))
    assert exc_503.value.status_code == 503
    assert "Traceback" not in exc_503.value.message


@respx.mock
def test_client_maps_connect_error_and_timeout() -> None:
    respx.get(f"{API_BASE}/v1/metrics").mock(side_effect=httpx.ConnectError("refused"))
    client = LifeAPIClient(api_url=API_BASE, api_key=FAKE_KEY)
    with pytest.raises(DashboardAPIError) as exc_conn:
        client.get_metrics(datetime.date(2026, 11, 1), datetime.date(2026, 11, 7))
    assert exc_conn.value.is_unreachable is True
    assert START_API_HINT in exc_conn.value.message

    respx.post(f"{API_BASE}/v1/agent/chat").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(DashboardAPIError) as exc_timeout:
        client.post_agent_chat("hello")
    assert exc_timeout.value.code == "timeout"
    assert FAKE_KEY not in str(exc_timeout.value)
