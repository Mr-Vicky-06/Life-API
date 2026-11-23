"""Integration tests for database migrations, role permissions, and vector storage."""
from __future__ import annotations

import datetime
import hashlib
from collections.abc import Generator

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.notes import Note, NoteChunk

TEST_DB_NAME = "life_test"
ADMIN_CONN_STR = "postgresql://life:life@127.0.0.1:5432/life"
TEST_RW_URL = f"postgresql+psycopg://life:life@127.0.0.1:5432/{TEST_DB_NAME}"
TEST_RO_URL = f"postgresql+psycopg://life_ro:life_ro@127.0.0.1:5432/{TEST_DB_NAME}"


@pytest.fixture(scope="module")
def setup_test_db() -> Generator[Config, None, None]:
    """Create fresh life_test database and return configured Alembic Config."""
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);")
            cur.execute(f"CREATE DATABASE {TEST_DB_NAME};")
            cur.execute(f"GRANT ALL PRIVILEGES ON DATABASE {TEST_DB_NAME} TO life;")
            cur.execute(f"GRANT CONNECT ON DATABASE {TEST_DB_NAME} TO life_ro;")

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_RW_URL)
    yield cfg

    # Cleanup connections & drop test DB after module tests
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);")


def test_migration_upgrade_on_empty_db(setup_test_db: Config):
    """Asserts that running alembic upgrade head on an empty DB succeeds."""
    cfg = setup_test_db
    command.upgrade(cfg, "head")

    engine = create_engine(TEST_RW_URL)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    views = set(inspector.get_view_names())

    expected_tables = {
        "health_daily",
        "github_commits",
        "reading_log",
        "screen_time",
        "notes",
        "note_chunks",
        "query_log",
        "alembic_version",
    }
    expected_views = {
        "v_daily_summary",
        "v_commits",
        "v_screen_time",
        "v_reading",
    }

    assert expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}"
    assert expected_views.issubset(views), f"Missing views: {expected_views - views}"
    engine.dispose()


def test_migration_downgrade_and_reupgrade(setup_test_db: Config):
    """Asserts that downgrade base drops objects and subsequent upgrade head restores them."""
    cfg = setup_test_db
    engine = create_engine(TEST_RW_URL)

    # Downgrade to base
    command.downgrade(cfg, "base")
    inspector = inspect(engine)
    remaining_tables = set(inspector.get_table_names())
    remaining_views = set(inspector.get_view_names())

    assert len(remaining_views) == 0
    assert remaining_tables.issubset({"alembic_version"})

    # Re-upgrade to head
    command.upgrade(cfg, "head")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    views = set(inspector.get_view_names())

    assert "health_daily" in tables
    assert "note_chunks" in tables
    assert "v_daily_summary" in views
    engine.dispose()


def test_life_ro_can_select_views(setup_test_db: Config):
    """Asserts that life_ro role can select from all 4 allowlisted views."""
    engine_ro = create_engine(
        TEST_RO_URL,
        connect_args={"options": "-c default_transaction_read_only=on"},
    )
    views = ["v_daily_summary", "v_commits", "v_screen_time", "v_reading"]

    with Session(bind=engine_ro) as session:
        for view in views:
            result = session.execute(text(f"SELECT count(*) FROM {view}")).scalar()
            assert result == 0

    engine_ro.dispose()


def test_life_ro_cannot_insert_or_select_notes(setup_test_db: Config):
    """Asserts that life_ro role cannot insert into tables and cannot select from notes."""
    engine_ro = create_engine(
        TEST_RO_URL,
        connect_args={"options": "-c default_transaction_read_only=on"},
    )

    # 1. Test insert is blocked
    with Session(bind=engine_ro) as session:
        with pytest.raises(DBAPIError) as exc_info:
            session.execute(
                text("INSERT INTO health_daily (date) VALUES ('2026-01-01')")
            )
            session.commit()
        # Should fail with read-only transaction error or permission error
        err_msg = str(exc_info.value).lower()
        assert (
            "read-only transaction" in err_msg
            or "permission denied" in err_msg
        )

    # 2. Test select from base table 'notes' is forbidden
    with Session(bind=engine_ro) as session:
        with pytest.raises(DBAPIError) as exc_info:
            session.execute(text("SELECT * FROM notes"))
        assert "permission denied" in str(exc_info.value).lower()

    engine_ro.dispose()


def test_vector_insert_and_tsv_autogenerated(setup_test_db: Config):
    """Asserts that vector(384) insert works on note_chunks and tsv is auto-generated."""
    engine_rw = create_engine(TEST_RW_URL)

    with Session(bind=engine_rw) as session:
        content = "Exploring pgvector and full-text search integration in Life-API."
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        note = Note(
            ts=datetime.datetime.now(datetime.UTC),
            note_date=datetime.date(2026, 1, 1),
            source_type="journal",
            content=content,
            content_hash=content_hash,
        )
        session.add(note)
        session.flush()

        embedding = [0.05] * 384
        chunk = NoteChunk(
            note_id=note.id,
            chunk_idx=0,
            content=content,
            chunk_metadata={"source": "pytest"},
            embedding=embedding,
        )
        session.add(chunk)
        session.commit()

        # Query back and inspect generated tsv and cosine distance
        query = text(
            "SELECT id, tsv, embedding <=> :query_emb AS dist "
            "FROM note_chunks WHERE id = :chunk_id"
        )
        row = session.execute(
            query,
            {"query_emb": str(embedding), "chunk_id": chunk.id},
        ).fetchone()

        assert row is not None
        assert row.tsv is not None
        assert "search" in str(row.tsv)
        assert abs(float(row.dist) - 0.0) < 1e-5

    engine_rw.dispose()
