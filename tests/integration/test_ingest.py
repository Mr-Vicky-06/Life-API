"""Integration tests for data ingestion endpoints, loaders, and seed idempotency."""
from __future__ import annotations

import os
from collections.abc import Generator

import httpx
import psycopg
import pytest
import respx
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import reset_engines
from app.main import app
from scripts.seed import seed_database

DB_PORT = os.getenv("DB_PORT", "5432")
TEST_DB_NAME = "life_test"
ADMIN_CONN_STR = f"postgresql://life:life@127.0.0.1:{DB_PORT}/life"
TEST_RW_URL = f"postgresql+psycopg://life:life@127.0.0.1:{DB_PORT}/{TEST_DB_NAME}"
TEST_RO_URL = f"postgresql+psycopg://life_ro:life_ro@127.0.0.1:{DB_PORT}/{TEST_DB_NAME}"


@pytest.fixture(scope="module")
def setup_test_db() -> Generator[Config, None, None]:
    """Create fresh life_test database with migrations applied."""
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);")
            cur.execute(f"CREATE DATABASE {TEST_DB_NAME};")
            cur.execute(f"GRANT ALL PRIVILEGES ON DATABASE {TEST_DB_NAME} TO life;")
            cur.execute(f"GRANT CONNECT ON DATABASE {TEST_DB_NAME} TO life_ro;")

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_RW_URL)
    command.upgrade(cfg, "head")

    # Override settings for tests
    settings = get_settings()
    settings.app_api_key = "test-key"
    settings.database_url = TEST_RW_URL
    settings.database_url_ro = TEST_RO_URL
    reset_engines()

    yield cfg

    reset_engines()
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);")


@pytest.fixture
def client(setup_test_db: Config) -> TestClient:
    return TestClient(app)


def test_auth_header_required(client: TestClient):
    """Endpoints require X-API-Key and return 401 with standard error envelope when invalid."""
    # Missing key
    resp = client.post("/v1/ingest/notes", json=[])
    assert resp.status_code == 401
    err = resp.json()["error"]
    assert err["code"] == "unauthorized"

    # Invalid key
    resp = client.post("/v1/ingest/notes", json=[], headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401
    err = resp.json()["error"]
    assert err["code"] == "unauthorized"


def test_health_csv_ingest_and_idempotency(client: TestClient):
    """Uploading health CSV ingests records and reports bad rows in errors without failing."""
    csv_data = """date,sleep_hours,sleep_score,deep_sleep_min,hrv_ms,resting_hr,steps,source
2026-01-10,7.5,85,60,55.2,58,8500,csv
2026-01-11,8.0,90,75,62.1,56,9200,csv
bad_date,not_a_number,abc,def,ghi,jkl,mno,csv
"""
    headers = {"X-API-Key": "test-key"}
    files = {"file": ("health.csv", csv_data, "text/csv")}

    # 1. First upload
    resp = client.post("/v1/ingest/health", files=files, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "health"
    assert data["inserted"] == 2
    assert len(data["errors"]) >= 1  # Bad row reported in errors

    # 2. Duplicate upload: should update existing and insert 0 new rows
    files2 = {"file": ("health.csv", csv_data, "text/csv")}
    resp2 = client.post("/v1/ingest/health", files=files2, headers=headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["inserted"] == 0
    assert data2["updated"] == 2


def test_reading_and_screen_time_ingest(client: TestClient):
    """Test reading and screen time CSV upload endpoints."""
    headers = {"X-API-Key": "test-key"}

    # Reading CSV
    reading_csv = """date,title,pages_read,minutes
2026-01-10,Atomic Habits,25,30
2026-01-11,Deep Work,18,25
"""
    resp_r = client.post(
        "/v1/ingest/reading",
        files={"file": ("reading.csv", reading_csv, "text/csv")},
        headers=headers,
    )
    assert resp_r.status_code == 200
    assert resp_r.json()["inserted"] == 2

    # Screen time CSV
    screen_csv = """date,category,minutes
2026-01-10,Productivity,180
2026-01-10,Entertainment,60
"""
    resp_s = client.post(
        "/v1/ingest/screen_time",
        files={"file": ("screen.csv", screen_csv, "text/csv")},
        headers=headers,
    )
    assert resp_s.status_code == 200
    assert resp_s.json()["inserted"] == 2


@respx.mock
def test_github_ingest_mocked(client: TestClient):
    """Test GitHub commit ingestion with respx mocking."""
    settings = get_settings()
    settings.github_username = "test-user"
    settings.github_token = "test-token"

    respx.get("https://api.github.com/users/test-user/events").mock(
        return_value=httpx.Response(
            200,
            json=[{
                "type": "PushEvent",
                "repo": {"name": "test-user/test-repo"},
            }],
        )
    )

    commits_data = [{
        "sha": "abc123def456",
        "commit": {
            "author": {"date": "2026-01-10T14:30:00Z"},
            "message": "feat: add initial feature",
        },
        "stats": {"additions": 50, "deletions": 10},
    }]

    respx.get("https://api.github.com/repos/test-user/test-repo/commits").mock(
        return_value=httpx.Response(200, json=commits_data)
    )

    resp = client.post("/v1/ingest/github", json={"days": 30}, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["inserted"] == 1


def test_github_ingest_no_token_warning(client: TestClient):
    """Missing token skips GitHub sync with warning in errors."""
    settings = get_settings()
    settings.github_token = ""

    resp = client.post("/v1/ingest/github", json={"days": 30}, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["inserted"] == 0
    assert any("not configured" in e for e in data["errors"])


def test_notes_ingest_deduplication(client: TestClient):
    """Notes ingest generates chunks and deduplicates by content hash."""
    headers = {"X-API-Key": "test-key"}
    payload = [
        {
            "ts": "2026-01-10T20:00:00Z",
            "source_type": "journal",
            "content": "Had an insightful discussion on vector databases and embeddings.",
        }
    ]

    # First insert
    resp1 = client.post("/v1/ingest/notes", json=payload, headers=headers)
    assert resp1.status_code == 200
    assert resp1.json()["inserted"] == 1
    assert resp1.json()["skipped"] == 0

    # Duplicate insert
    resp2 = client.post("/v1/ingest/notes", json=payload, headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["inserted"] == 0
    assert resp2.json()["skipped"] == 1


def test_seed_idempotency(setup_test_db: Config):
    """Running seed_database() twice produces identical table row counts."""
    engine = create_engine(TEST_RW_URL)

    # First seed run
    seed_database()

    count_query = text("""
        SELECT 
            (SELECT count(*) FROM health_daily) AS health,
            (SELECT count(*) FROM github_commits) AS commits,
            (SELECT count(*) FROM reading_log) AS reading,
            (SELECT count(*) FROM screen_time) AS screen,
            (SELECT count(*) FROM notes) AS notes,
            (SELECT count(*) FROM note_chunks) AS chunks
    """)

    with Session(bind=engine) as session:
        counts_a = session.execute(count_query).mappings().one()

    # Second seed run
    seed_database()

    with Session(bind=engine) as session:
        counts_b = session.execute(count_query).mappings().one()

    assert counts_a == counts_b, f"Counts differ between runs: {counts_a} vs {counts_b}"
    assert counts_a["health"] >= 90
    assert counts_a["notes"] >= 40
    assert counts_a["chunks"] >= counts_a["notes"]
    engine.dispose()
