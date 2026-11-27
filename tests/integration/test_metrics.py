"""Integration tests for GET /v1/metrics endpoint against life_test DB."""
from __future__ import annotations

import datetime
import os
from collections.abc import Generator

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes_metrics import ALLOWED_METRIC_COLUMNS
from app.config import get_settings
from app.db import reset_engines, rw_engine
from app.main import app
from app.schemas.metrics import MetricsResponse
from scripts.seed import seed_database

DB_PORT = os.getenv("DB_PORT", "5432")
TEST_DB_NAME = "life_test"
ADMIN_CONN_STR = f"postgresql://life:life@127.0.0.1:{DB_PORT}/life"
TEST_RW_URL = f"postgresql+psycopg://life:life@127.0.0.1:{DB_PORT}/{TEST_DB_NAME}"
TEST_RO_URL = f"postgresql+psycopg://life_ro:life_ro@127.0.0.1:{DB_PORT}/{TEST_DB_NAME}"
SEED_END = datetime.date(2026, 11, 23)


@pytest.fixture(scope="module")
def metrics_test_db() -> Generator[Config, None, None]:
    """Create isolated life_test database seeded deterministically for metrics tests."""
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
    )
    settings.app_api_key = "test-key"
    settings.database_url = TEST_RW_URL
    settings.database_url_ro = TEST_RO_URL
    settings.seed_end_date = SEED_END
    reset_engines()

    seed_database(end_date=SEED_END)
    yield cfg

    (
        settings.app_api_key,
        settings.database_url,
        settings.database_url_ro,
        settings.seed_end_date,
    ) = orig
    reset_engines()
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);")


def _notes_count() -> int:
    with Session(bind=rw_engine()) as session:
        return int(session.execute(text("SELECT count(*) FROM notes")).scalar_one())


def test_metrics_requires_api_key(metrics_test_db: Config):
    client = TestClient(app)
    resp = client.get("/v1/metrics?from=2026-11-01&to=2026-11-07")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_metrics_values_equal_direct_sql_and_validate_schema(metrics_test_db: Config):
    client = TestClient(app)
    resp = client.get(
        "/v1/metrics?from=2026-11-01&to=2026-11-07&metrics=sleep_hours,commits",
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 200
    parsed = MetricsResponse.model_validate(resp.json())
    assert parsed.from_date == datetime.date(2026, 11, 1)
    assert parsed.to_date == datetime.date(2026, 11, 7)

    with Session(bind=rw_engine()) as session:
        expected_rows = (
            session.execute(
                text(
                    "SELECT date, sleep_hours, commits FROM v_daily_summary "
                    "WHERE date >= '2026-11-01' AND date <= '2026-11-07' ORDER BY date"
                )
            )
            .mappings()
            .all()
        )

    assert len(parsed.rows) == len(expected_rows) == 7
    for actual, expected in zip(parsed.rows, expected_rows, strict=True):
        assert set(actual.keys()) == {"date", "sleep_hours", "commits"}
        assert actual["date"] == expected["date"].isoformat()
        assert actual["sleep_hours"] == pytest.approx(float(expected["sleep_hours"]))
        assert actual["commits"] == int(expected["commits"])


def test_metrics_default_returns_all_allowed_columns_and_skips_missing_dates(
    metrics_test_db: Config,
):
    client = TestClient(app)
    # Seed ends at 2026-11-23; dates 2026-11-24..2026-11-26 have no rows and must be absent.
    resp = client.get(
        "/v1/metrics?from=2026-11-21&to=2026-11-26",
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 200
    parsed = MetricsResponse.model_validate(resp.json())
    assert [row["date"] for row in parsed.rows] == ["2026-11-21", "2026-11-22", "2026-11-23"]
    expected_keys = {"date", *ALLOWED_METRIC_COLUMNS.keys()}
    for row in parsed.rows:
        assert set(row.keys()) == expected_keys


def test_metrics_validation_errors_and_sqli_safety(metrics_test_db: Config):
    client = TestClient(app)
    before_notes = _notes_count()

    # Unknown metric -> 422 naming allowed list
    r_unknown = client.get(
        "/v1/metrics?from=2026-11-01&to=2026-11-07&metrics=sleep_hours,mood",
        headers={"X-API-Key": "test-key"},
    )
    assert r_unknown.status_code == 422
    err_unknown = r_unknown.json()["error"]
    assert err_unknown["code"] == "validation_error"
    assert "sleep_hours" in err_unknown["message"]
    assert "screen_minutes" in err_unknown["message"]

    # from > to -> 422
    r_order = client.get(
        "/v1/metrics?from=2026-11-10&to=2026-11-01",
        headers={"X-API-Key": "test-key"},
    )
    assert r_order.status_code == 422
    assert r_order.json()["error"]["code"] == "validation_error"

    # Range > 366 days -> 422
    r_range = client.get(
        "/v1/metrics?from=2025-01-01&to=2026-01-03",
        headers={"X-API-Key": "test-key"},
    )
    assert r_range.status_code == 422
    assert r_range.json()["error"]["code"] == "validation_error"

    # SQL injection attempt in metric param -> 422 and notes untouched
    r_sqli = client.get(
        "/v1/metrics?from=2026-11-01&to=2026-11-07&metrics=steps; DROP TABLE notes",
        headers={"X-API-Key": "test-key"},
    )
    assert r_sqli.status_code == 422
    assert r_sqli.json()["error"]["code"] == "validation_error"
    assert _notes_count() == before_notes


def test_screen_time_requires_api_key(metrics_test_db: Config):
    client = TestClient(app)
    resp = client.get("/v1/screen-time?from=2026-11-01&to=2026-11-07")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_screen_time_matches_direct_sql_and_validates_range(metrics_test_db: Config):
    client = TestClient(app)
    resp = client.get(
        "/v1/screen-time?from=2026-11-01&to=2026-11-07",
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 200
    body = resp.json()

    with Session(bind=rw_engine()) as session:
        expected_rows = (
            session.execute(
                text(
                    "SELECT category, CAST(SUM(minutes) AS INTEGER) AS minutes "
                    "FROM v_screen_time "
                    "WHERE date >= '2026-11-01' AND date <= '2026-11-07' "
                    "GROUP BY category ORDER BY minutes DESC, category ASC"
                )
            )
            .mappings()
            .all()
        )

    assert len(body) == len(expected_rows) > 0
    for actual, expected in zip(body, expected_rows, strict=True):
        assert actual["category"] == expected["category"]
        assert actual["minutes"] == int(expected["minutes"])

    # Invalid ranges -> 422 validation_error
    r_order = client.get(
        "/v1/screen-time?from=2026-11-07&to=2026-11-01",
        headers={"X-API-Key": "test-key"},
    )
    assert r_order.status_code == 422
    assert r_order.json()["error"]["code"] == "validation_error"

    r_span = client.get(
        "/v1/screen-time?from=2025-01-01&to=2026-01-03",
        headers={"X-API-Key": "test-key"},
    )
    assert r_span.status_code == 422
    assert r_span.json()["error"]["code"] == "validation_error"
