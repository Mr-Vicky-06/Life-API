"""Integration and live tests for POST /v1/agent/chat endpoint."""
from __future__ import annotations

import datetime
import json
import os
import time
from collections.abc import Generator

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.react import clear_sessions, get_session_ids
from app.config import get_settings
from app.db import reset_engines, rw_engine
from app.gateway.llm import LLMResponse
from app.main import _rate_store, app
from app.schemas.agent import AgentResponse
from scripts.seed import seed_database

DB_PORT = os.getenv("DB_PORT", "5432")
TEST_DB_NAME = "life_test"
ADMIN_CONN_STR = f"postgresql://life:life@127.0.0.1:{DB_PORT}/life"
TEST_RW_URL = f"postgresql+psycopg://life:life@127.0.0.1:{DB_PORT}/{TEST_DB_NAME}"
TEST_RO_URL = f"postgresql+psycopg://life_ro:life_ro@127.0.0.1:{DB_PORT}/{TEST_DB_NAME}"
SEED_END = datetime.date(2026, 11, 23)


@pytest.fixture(scope="module")
def agent_test_db() -> Generator[Config, None, None]:
    """Create isolated life_test database seeded deterministically for agent tests."""
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);")
            cur.execute(f"CREATE DATABASE {TEST_DB_NAME};")
            cur.execute(f"GRANT ALL PRIVILEGES ON DATABASE {TEST_DB_NAME} TO life;")
            cur.execute(f"GRANT CONNECT ON DATABASE {TEST_DB_NAME} TO life_ro;")

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_RW_URL)
    command.upgrade(cfg, "head")

    settings = get_settings()
    orig = (
        settings.app_api_key,
        settings.database_url,
        settings.database_url_ro,
        settings.seed_end_date,
        settings.reference_date,
    )
    settings.app_api_key = "test-key"
    settings.database_url = TEST_RW_URL
    settings.database_url_ro = TEST_RO_URL
    settings.seed_end_date = SEED_END
    settings.reference_date = SEED_END
    reset_engines()

    seed_database(end_date=SEED_END)
    yield cfg

    (
        settings.app_api_key,
        settings.database_url,
        settings.database_url_ro,
        settings.seed_end_date,
        settings.reference_date,
    ) = orig
    reset_engines()
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);")


@pytest.fixture(autouse=True)
def _clean_agent_sessions() -> Generator[None, None, None]:
    clear_sessions()
    _rate_store.clear()
    yield
    clear_sessions()
    _rate_store.clear()


def test_agent_requires_api_key(agent_test_db: Config):
    client = TestClient(app)
    r_missing = client.post("/v1/agent/chat", json={"message": "hello"})
    assert r_missing.status_code == 401
    assert r_missing.json()["error"]["code"] == "unauthorized"

    r_wrong = client.post(
        "/v1/agent/chat",
        json={"message": "hello"},
        headers={"X-API-Key": "wrong-key"},
    )
    assert r_wrong.status_code == 401
    assert r_wrong.json()["error"]["code"] == "unauthorized"


def test_agent_request_validation_errors(agent_test_db: Config):
    client = TestClient(app)
    headers = {"X-API-Key": "test-key"}

    assert client.post("/v1/agent/chat", json={"message": ""}, headers=headers).status_code == 422
    assert (
        client.post("/v1/agent/chat", json={"message": "   "}, headers=headers).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/agent/chat", json={"message": "x" * 801}, headers=headers
        ).status_code
        == 422
    )
    for bad_sid in ("", "bad id!", "../hack", "a" * 65):
        resp = client.post(
            "/v1/agent/chat",
            json={"message": "Hello", "session_id": bad_sid},
            headers=headers,
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"


def test_agent_full_flow_with_real_metrics_and_session_continuity(
    agent_test_db: Config,
    monkeypatch: pytest.MonkeyPatch,
):
    captured_threads: list[list[dict[str, str]]] = []

    def fake_call_llm(messages=None, prompt=None, **kwargs):
        msgs = list(messages or [{"role": "user", "content": prompt or ""}])
        captured_threads.append(msgs)
        last_content = msgs[-1]["content"]
        if "Observation (get_metrics):" not in last_content:
            return LLMResponse(
                content=json.dumps({
                    "thought": "Fetch Nov 2 sleep via get_metrics.",
                    "action": "get_metrics",
                    "action_input": {
                        "from": "2026-11-02",
                        "to": "2026-11-02",
                        "metrics": ["sleep_hours"],
                    },
                }),
                model="stub",
                latency_ms=5.0,
            )
        return LLMResponse(
            content=json.dumps({
                "thought": "Answer from DB observation.",
                "action": "final",
                "action_input": {"answer": "On 2026-11-02, your sleep was 8.01 hours."},
            }),
            model="stub",
            latency_ms=5.0,
        )

    monkeypatch.setattr("app.gateway.router.call_llm", fake_call_llm)
    client = TestClient(app)
    headers = {"X-API-Key": "test-key"}

    resp1 = client.post(
        "/v1/agent/chat",
        json={"message": "How much did I sleep on 2026-11-02?", "session_id": "sess-1"},
        headers=headers,
    )
    assert resp1.status_code == 200
    parsed1 = AgentResponse.model_validate(resp1.json())
    assert parsed1.session_id == "sess-1"
    assert [s.action for s in parsed1.steps] == ["get_metrics", "final"]
    assert "8.01" in parsed1.answer

    # Second call with same session_id -> stub prompt sees previous user and answer turns
    def fake_turn2(messages=None, prompt=None, **kwargs):
        msgs = list(messages or [{"role": "user", "content": prompt or ""}])
        captured_threads.append(msgs)
        return LLMResponse(
            content=json.dumps({
                "thought": "Use context.",
                "action": "final",
                "action_input": {"answer": "Previously we noted 2026-11-02."},
            }),
            model="stub",
            latency_ms=4.0,
        )

    monkeypatch.setattr("app.gateway.router.call_llm", fake_turn2)
    resp2 = client.post(
        "/v1/agent/chat",
        json={"message": "Remind me which date we checked?", "session_id": "sess-1"},
        headers=headers,
    )
    assert resp2.status_code == 200
    turn2_messages = captured_threads[-1]
    assert {"role": "user", "content": "How much did I sleep on 2026-11-02?"} in turn2_messages
    assert {
        "role": "assistant",
        "content": "On 2026-11-02, your sleep was 8.01 hours.",
    } in turn2_messages


def test_agent_history_capped_at_6_turns_and_sessions_capped_at_100(
    agent_test_db: Config,
    monkeypatch: pytest.MonkeyPatch,
):
    seen_histories: list[list[dict[str, str]]] = []

    def fake_call_llm(messages=None, prompt=None, **kwargs):
        msgs = list(messages or [{"role": "user", "content": prompt or ""}])
        seen_histories.append(msgs)
        return LLMResponse(
            content=json.dumps({
                "thought": "reply",
                "action": "final",
                "action_input": {"answer": f"Ack: {msgs[-1]['content']}"},
            }),
            model="stub",
            latency_ms=2.0,
        )

    monkeypatch.setattr("app.gateway.router.call_llm", fake_call_llm)
    client = TestClient(app)
    headers = {"X-API-Key": "test-key"}

    # Send 8 turns to same session; 9th turn prompt must contain turns 3..8 (6 turns max)
    for i in range(1, 9):
        r = client.post(
            "/v1/agent/chat",
            json={"message": f"turn-{i}", "session_id": "hist-cap"},
            headers=headers,
        )
        assert r.status_code == 200

    r9 = client.post(
        "/v1/agent/chat",
        json={"message": "turn-9", "session_id": "hist-cap"},
        headers=headers,
    )
    assert r9.status_code == 200
    turn9_msgs = seen_histories[-1]
    prior_user_contents = [m["content"] for m in turn9_msgs[:-1] if m["role"] == "user"]
    assert prior_user_contents == ["turn-3", "turn-4", "turn-5", "turn-6", "turn-7", "turn-8"]

    # Create 105 distinct sessions -> LRU eviction keeps count capped at 100
    clear_sessions()
    for idx in range(105):
        _rate_store.clear()
        rs = client.post(
            "/v1/agent/chat",
            json={"message": f"hi {idx}", "session_id": f"s-{idx}"},
            headers=headers,
        )
        assert rs.status_code == 200

    ids = get_session_ids()
    assert len(ids) == 100
    assert "s-0" not in ids
    assert "s-4" not in ids
    assert "s-104" in ids


@pytest.mark.live
def test_live_agent_average_sleep_on_commit_days(agent_test_db: Config):
    """Live Ollama test: real model selects sql_query then final for commit-day sleep."""
    with Session(bind=rw_engine()) as session:
        expected_avg = float(
            session.execute(
                text(
                    "SELECT round(avg(sleep_hours), 2) "
                    "FROM v_daily_summary WHERE commits > 0"
                )
            ).scalar_one()
        )

    client = TestClient(app)
    t0 = time.perf_counter()
    resp = client.post(
        "/v1/agent/chat",
        json={"message": "What was my average sleep on days I pushed code?"},
        headers={"X-API-Key": "test-key"},
    )
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert resp.status_code == 200
    parsed = AgentResponse.model_validate(resp.json())
    actions = [s.action for s in parsed.steps]
    print(f"LIVE AGENT ({latency_ms:.0f} ms) actions={actions} answer={parsed.answer!r}")
    for idx, step in enumerate(parsed.steps, start=1):
        print(
            f"  step {idx}: action={step.action} input={step.action_input} thought={step.thought}"
        )

    assert "sql_query" in actions
    assert actions[-1] == "final"
    assert str(round(expected_avg, 1)) in parsed.answer or str(expected_avg) in parsed.answer
