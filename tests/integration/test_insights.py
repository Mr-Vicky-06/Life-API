"""Integration and live tests for GET /v1/insights/daily endpoint."""
from __future__ import annotations

import datetime
import time
from collections.abc import Generator

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes_insights import clear_insights_cache
from app.config import get_settings
from app.db import reset_engines, rw_engine
from app.gateway.exceptions import LLMUnavailable
from app.gateway.llm import LLMResponse
from app.main import app
from app.schemas.insights import DailyInsight
from scripts.seed import seed_database

TEST_DB_NAME = "life_test"
ADMIN_CONN_STR = "postgresql://life:life@127.0.0.1:5432/life"
TEST_RW_URL = f"postgresql+psycopg://life:life@127.0.0.1:5432/{TEST_DB_NAME}"
TEST_RO_URL = f"postgresql+psycopg://life_ro:life_ro@127.0.0.1:5432/{TEST_DB_NAME}"
SEED_END = datetime.date(2026, 11, 23)


@pytest.fixture(scope="module")
def insights_test_db() -> Generator[Config, None, None]:
    """Create isolated life_test database seeded deterministically for insights tests."""
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
def _reset_cache_per_test() -> Generator[None, None, None]:
    clear_insights_cache()
    yield
    clear_insights_cache()


def _db_day_metrics(target_date: datetime.date) -> dict[str, float | int]:
    with Session(bind=rw_engine()) as session:
        row = (
            session.execute(
                text(
                    "SELECT sleep_hours, commits, reading_minutes, steps, screen_minutes "
                    "FROM v_daily_summary WHERE date = :d"
                ),
                {"d": target_date},
            )
            .mappings()
            .one()
        )
        return {
            "sleep_hours": float(row["sleep_hours"]),
            "github_commits": int(row["commits"]),
            "reading_minutes": int(row["reading_minutes"]),
            "steps": int(row["steps"]),
            "screen_minutes": int(row["screen_minutes"]),
        }


def test_insights_requires_api_key(insights_test_db: Config):
    client = TestClient(app)
    resp = client.get("/v1/insights/daily?date=2026-11-02")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_insights_not_found_returns_404(insights_test_db: Config):
    client = TestClient(app)
    resp = client.get("/v1/insights/daily?date=2025-01-01", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 404
    err = resp.json()["error"]
    assert err["code"] == "not_found"


def test_insights_numbers_match_db_cache_hit_and_no_note_text_in_prompt(
    insights_test_db: Config,
    monkeypatch: pytest.MonkeyPatch,
):
    target_date = datetime.date(2026, 11, 2)
    db_metrics = _db_day_metrics(target_date)

    with Session(bind=rw_engine()) as session:
        sample_notes = session.execute(text("SELECT content FROM notes LIMIT 20")).scalars().all()
        assert len(sample_notes) >= 5

    captured_prompts: list[tuple[str | None, str | None]] = []

    def fake_call_llm(prompt: str | None = None, system: str | None = None, **kwargs):
        captured_prompts.append((system, prompt))
        payload = (
            f'{{"summary": "On {target_date.isoformat()}, you slept {db_metrics["sleep_hours"]} '
            f'hours and made {db_metrics["github_commits"]} commits.", '
            f'"insights": "Walked {db_metrics["steps"]} steps and read for '
            f'{db_metrics["reading_minutes"]} minutes."}}'
        )
        return LLMResponse(content=payload, model="stub-model", latency_ms=10.0)

    monkeypatch.setattr("app.gateway.structured.call_llm", fake_call_llm)

    client = TestClient(app)
    resp1 = client.get("/v1/insights/daily?date=2026-11-02", headers={"X-API-Key": "test-key"})
    assert resp1.status_code == 200
    parsed1 = DailyInsight.model_validate(resp1.json())
    assert parsed1.timestamp == target_date
    assert parsed1.metrics == db_metrics
    assert len(captured_prompts) == 1

    sys_txt, usr_txt = captured_prompts[0]
    combined_prompt = f"{sys_txt or ''}\n{usr_txt or ''}"
    for note_content in sample_notes:
        snippet = note_content[:40].strip()
        if snippet:
            assert snippet not in combined_prompt

    # Second call with identical DB metrics hits the cache (stub still called once)
    resp2 = client.get("/v1/insights/daily?date=2026-11-02", headers={"X-API-Key": "test-key"})
    assert resp2.status_code == 200
    assert resp2.json() == resp1.json()
    assert len(captured_prompts) == 1


def test_insights_default_date_and_cache_invalidation_on_data_change(
    insights_test_db: Config,
    monkeypatch: pytest.MonkeyPatch,
):
    call_count = 0

    def fake_call_llm(prompt: str | None = None, system: str | None = None, **kwargs):
        nonlocal call_count
        call_count += 1
        # Use no extra numbers so numeric check succeeds cleanly on both calls
        return LLMResponse(
            content=(
                '{"summary": "Steady productivity and balanced daily metrics recorded.", '
                '"insights": "Activity and sleep align well with your recent weekly average."}'
            ),
            model="stub-model",
            latency_ms=12.0,
        )

    monkeypatch.setattr("app.gateway.structured.call_llm", fake_call_llm)
    client = TestClient(app)

    # Omitted date resolves to latest date <= REFERENCE_DATE (2026-11-23)
    resp1 = client.get("/v1/insights/daily", headers={"X-API-Key": "test-key"})
    assert resp1.status_code == 200
    parsed1 = DailyInsight.model_validate(resp1.json())
    assert parsed1.timestamp == SEED_END
    assert call_count == 1

    orig_sleep = parsed1.metrics["sleep_hours"]
    new_sleep = round(float(orig_sleep) + 0.5, 2)
    try:
        with Session(bind=rw_engine()) as session:
            session.execute(
                text("UPDATE health_daily SET sleep_hours = :s WHERE date = :d"),
                {"s": new_sleep, "d": SEED_END},
            )
            session.commit()

        resp2 = client.get("/v1/insights/daily", headers={"X-API-Key": "test-key"})
        assert resp2.status_code == 200
        parsed2 = DailyInsight.model_validate(resp2.json())
        assert parsed2.metrics["sleep_hours"] == new_sleep
        assert call_count == 2
    finally:
        with Session(bind=rw_engine()) as session:
            session.execute(
                text("UPDATE health_daily SET sleep_hours = :s WHERE date = :d"),
                {"s": orig_sleep, "d": SEED_END},
            )
            session.commit()


def test_insights_invented_number_falls_back_to_template_without_caching(
    insights_test_db: Config,
    monkeypatch: pytest.MonkeyPatch,
):
    target_date = datetime.date(2026, 11, 2)
    db_metrics = _db_day_metrics(target_date)
    calls = 0

    def hallucinating_llm(**kwargs):
        nonlocal calls
        calls += 1
        return LLMResponse(
            content=(
                '{"summary": "You completed 99999 steps today.", '
                '"insights": "Everything improved by 88 percent."}'
            ),
            model="stub-model",
            latency_ms=15.0,
        )

    monkeypatch.setattr("app.gateway.structured.call_llm", hallucinating_llm)
    client = TestClient(app)

    resp1 = client.get("/v1/insights/daily?date=2026-11-02", headers={"X-API-Key": "test-key"})
    assert resp1.status_code == 200
    parsed1 = DailyInsight.model_validate(resp1.json())
    assert parsed1.metrics == db_metrics
    assert "99999" not in parsed1.summary
    assert "88" not in parsed1.insights
    assert str(db_metrics["steps"]) in parsed1.summary
    assert calls == 1

    # Fallback was NOT cached, so a subsequent call invokes the LLM path again
    resp2 = client.get("/v1/insights/daily?date=2026-11-02", headers={"X-API-Key": "test-key"})
    assert resp2.status_code == 200
    assert calls == 2


def test_insights_llm_down_returns_200_template_without_caching(
    insights_test_db: Config,
    monkeypatch: pytest.MonkeyPatch,
):
    target_date = datetime.date(2026, 11, 2)
    db_metrics = _db_day_metrics(target_date)
    calls = 0

    def failing_llm(**kwargs):
        nonlocal calls
        calls += 1
        raise LLMUnavailable("Ollama connection refused")

    monkeypatch.setattr("app.gateway.structured.call_llm", failing_llm)
    client = TestClient(app)

    resp1 = client.get("/v1/insights/daily?date=2026-11-02", headers={"X-API-Key": "test-key"})
    assert resp1.status_code == 200
    parsed1 = DailyInsight.model_validate(resp1.json())
    assert parsed1.metrics == db_metrics
    assert str(db_metrics["github_commits"]) in parsed1.summary
    calls_during_outage = calls
    assert calls_during_outage >= 1

    # Recover LLM -> next call must NOT serve uncached fallback; it succeeds via LLM
    def healthy_llm(**kwargs):
        nonlocal calls
        calls += 1
        return LLMResponse(
            content=(
                '{"summary": "Recovered narrative matching database records.", '
                '"insights": "Sleep and commits remained well balanced."}'
            ),
            model="stub-model",
            latency_ms=10.0,
        )

    monkeypatch.setattr("app.gateway.structured.call_llm", healthy_llm)
    resp2 = client.get("/v1/insights/daily?date=2026-11-02", headers={"X-API-Key": "test-key"})
    assert resp2.status_code == 200
    assert resp2.json()["summary"] == "Recovered narrative matching database records."
    assert calls == calls_during_outage + 1


@pytest.mark.live
def test_live_daily_insight(insights_test_db: Config):
    """Live Ollama test: real model generates DailyInsight for 2026-11-02."""
    target_date = datetime.date(2026, 11, 2)
    db_metrics = _db_day_metrics(target_date)
    client = TestClient(app)

    t0 = time.perf_counter()
    resp = client.get("/v1/insights/daily?date=2026-11-02", headers={"X-API-Key": "test-key"})
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert resp.status_code == 200
    parsed = DailyInsight.model_validate(resp.json())
    assert parsed.timestamp == target_date
    assert parsed.metrics == db_metrics
    print(f"LIVE DAILY INSIGHT ({latency_ms:.0f} ms): {resp.text}")
    assert latency_ms > 0.0
