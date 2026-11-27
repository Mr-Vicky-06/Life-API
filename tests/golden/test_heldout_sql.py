"""Verification tests for the 12 held-out benchmark oracle SQLs against seeded life_test DB."""
from __future__ import annotations

import json
import os
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import reset_engines
from app.main import app
from scripts.seed import seed_database
from tests.golden.heldout import HELDOUT_CASES, SEED_END, compute_heldout_expected

DB_PORT = os.getenv("DB_PORT", "5432")
TEST_DB_NAME = "life_test"
ADMIN_CONN_STR = f"postgresql://life:life@127.0.0.1:{DB_PORT}/life"
TEST_RW_URL = f"postgresql+psycopg://life:life@127.0.0.1:{DB_PORT}/{TEST_DB_NAME}"
TEST_RO_URL = f"postgresql+psycopg://life_ro:life_ro@127.0.0.1:{DB_PORT}/{TEST_DB_NAME}"


@pytest.fixture(scope="module")
def seeded_heldout_db() -> Generator[dict[int, list[list[Any]]], None, None]:
    """Create fresh life_test database, run migrations, and seed deterministic dataset."""
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
    expected = compute_heldout_expected()

    yield expected

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


@pytest.mark.parametrize(
    ("hid", "question", "sql"),
    HELDOUT_CASES,
    ids=[f"heldout_h{c[0]}" for c in HELDOUT_CASES],
)
def test_heldout_oracle_sql_matches_python_expected(
    seeded_heldout_db: dict[int, list[list[Any]]],
    monkeypatch: pytest.MonkeyPatch,
    hid: int,
    question: str,
    sql: str,
):
    """Stub LLM returning held-out expected SQL yields exact Python-verified results."""

    def fake_litellm_completion(**kwargs):
        resp_fmt = kwargs.get("response_format")
        if resp_fmt and resp_fmt.get("type") == "json_object":
            payload = json.dumps({"sql": sql, "explanation": f"Heldout oracle SQL for H{hid}."})
        else:
            payload = ""
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=payload))],
            usage=SimpleNamespace(completion_tokens=20),
        )

    monkeypatch.setattr("app.gateway.llm.litellm.completion", fake_litellm_completion)

    client = TestClient(app)
    resp = client.post(
        "/v1/query",
        headers={"X-API-Key": "test-key"},
        json={"question": question},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rows"] == seeded_heldout_db[hid]
