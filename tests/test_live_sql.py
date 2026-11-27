"""Optional live-LLM smoke test for Text-to-SQL pipeline."""
from __future__ import annotations

import datetime
import os
from collections.abc import Generator

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from app.config import get_settings
from app.db import reset_engines
from app.sql_agent.executor import execute_readonly_sql
from app.sql_agent.generator import generate_sql
from app.sql_agent.validator import validate_sql
from scripts.seed import seed_database

DB_PORT = os.getenv("DB_PORT", "5432")
TEST_DB_NAME = "life_test"
ADMIN_CONN_STR = f"postgresql://life:life@127.0.0.1:{DB_PORT}/life"
TEST_RW_URL = f"postgresql+psycopg://life:life@127.0.0.1:{DB_PORT}/{TEST_DB_NAME}"
TEST_RO_URL = f"postgresql+psycopg://life_ro:life_ro@127.0.0.1:{DB_PORT}/{TEST_DB_NAME}"
SEED_END = datetime.date(2026, 11, 23)


@pytest.fixture(scope="module")
def live_sql_test_db() -> Generator[Config, None, None]:
    """Create isolated life_test DB with deterministic seed for live SQL smoke test."""
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
    orig = (settings.database_url, settings.database_url_ro, settings.seed_end_date)
    settings.database_url = TEST_RW_URL
    settings.database_url_ro = TEST_RO_URL
    settings.seed_end_date = SEED_END
    reset_engines()

    seed_database(end_date=SEED_END)
    yield cfg

    settings.database_url, settings.database_url_ro, settings.seed_end_date = orig
    reset_engines()
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);")


@pytest.mark.live
def test_live_ollama_text_to_sql_smoke(live_sql_test_db: Config):
    """Smoke test: real llama3.1:8b generates valid SQL executed on read-only view."""
    generated = generate_sql("What was my average sleep on days with commits > 0?")
    safe_sql = validate_sql(generated.sql)
    res = execute_readonly_sql(safe_sql)

    assert res.row_count == 1
    assert len(res.rows[0]) >= 1
    val = res.rows[0][0]
    assert isinstance(val, (int, float))
    assert 4.0 <= float(val) <= 10.0
