"""Security tests verifying PostgreSQL life_ro enforcement and 5s statement timeout."""
from __future__ import annotations

import os
import time
from collections.abc import Generator

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import reset_engines, ro_engine
from app.sql_agent.executor import execute_readonly_sql

DB_PORT = os.getenv("DB_PORT", "5432")
TEST_DB_NAME = "life_test"
ADMIN_CONN_STR = f"postgresql://life:life@127.0.0.1:{DB_PORT}/life"
TEST_RW_URL = f"postgresql+psycopg://life:life@127.0.0.1:{DB_PORT}/{TEST_DB_NAME}"
TEST_RO_URL = f"postgresql+psycopg://life_ro:life_ro@127.0.0.1:{DB_PORT}/{TEST_DB_NAME}"


@pytest.fixture(scope="module")
def setup_ro_test_db() -> Generator[Config, None, None]:
    """Create fresh life_test database with migrations applied and RO engine pointed to it."""
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
    orig_rw, orig_ro = settings.database_url, settings.database_url_ro
    settings.database_url = TEST_RW_URL
    settings.database_url_ro = TEST_RO_URL
    reset_engines()

    yield cfg

    settings.database_url = orig_rw
    settings.database_url_ro = orig_ro
    reset_engines()
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);")


@pytest.mark.parametrize(
    "mutating_sql",
    [
        "INSERT INTO health_daily (date, sleep_hours) VALUES ('2026-01-01', 7.5)",
        "UPDATE health_daily SET sleep_hours = 8.0 WHERE date = '2026-01-01'",
        "DELETE FROM notes",
        "CREATE TABLE rogue_table (id int)",
        "SELECT * FROM notes",
    ],
)
def test_life_ro_cannot_write_or_access_base_tables_even_bypassing_validator(
    setup_ro_test_db: Config, mutating_sql: str
):
    """Defense in depth: even bypassing validator, life_ro blocks writes and base tables."""
    with Session(bind=ro_engine()) as session:
        with pytest.raises(DBAPIError) as exc_info:
            execute_readonly_sql(mutating_sql, session=session)
        msg = str(exc_info.value).lower()
        assert (
            "read-only transaction" in msg
            or "permission denied" in msg
        )


def test_ro_executor_enforces_5s_statement_timeout(setup_ro_test_db: Config):
    """A long-running query (pg_sleep(10)) is cancelled by the 5s statement_timeout."""
    t0 = time.perf_counter()
    with pytest.raises(DBAPIError) as exc_info:
        execute_readonly_sql("SELECT pg_sleep(10)")
    elapsed = time.perf_counter() - t0

    msg = str(exc_info.value).lower()
    assert "statement timeout" in msg or "canceling statement" in msg
    assert 4.0 <= elapsed < 8.5, f"Expected ~5s cancellation, got {elapsed:.2f}s"
