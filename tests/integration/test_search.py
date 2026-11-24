"""Integration tests for hybrid search, RRF fusion, and /v1/search API."""
from __future__ import annotations

import datetime
from collections.abc import Generator

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_rw_engine, reset_engines
from app.main import app
from app.models.notes import Note, NoteChunk
from app.rag.hybrid import hybrid_search

TEST_DB_NAME = "life_test"
ADMIN_CONN_STR = "postgresql://life:life@127.0.0.1:5432/life"
TEST_RW_URL = f"postgresql+psycopg://life:life@127.0.0.1:5432/{TEST_DB_NAME}"
TEST_RO_URL = f"postgresql+psycopg://life_ro:life_ro@127.0.0.1:5432/{TEST_DB_NAME}"


@pytest.fixture(scope="module")
def setup_search_db() -> Generator[Config, None, None]:
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

    settings = get_settings()
    settings.app_api_key = "test-key"
    settings.database_url = TEST_RW_URL
    settings.database_url_ro = TEST_RO_URL
    reset_engines()

    yield cfg

    reset_engines()


def _make_unit_vector(idx: int, dim: int = 384) -> list[float]:
    vec = [0.0] * dim
    vec[idx % dim] = 1.0
    return vec


@pytest.fixture(scope="module")
def seeded_search_notes(setup_search_db: Config) -> dict[str, int]:
    """Populate life_test with crafted notes demonstrating vector-only, term-only, and fused behavior."""
    engine = get_rw_engine()
    created_ids: dict[str, int] = {}

    with Session(engine) as session:
        # Note 1: Semantic vector match for query (embedding at dim 0), but no keyword "entanglement"
        n1 = Note(
            ts=datetime.datetime(2026, 1, 10, 10, 0, tzinfo=datetime.UTC),
            note_date=datetime.date(2026, 1, 10),
            source_type="journal",
            content="Superconducting quantum devices and magnetic flux calculations.",
            content_hash="hash_note_1",
        )
        session.add(n1)
        session.flush()
        c1 = NoteChunk(
            note_id=n1.id,
            chunk_idx=0,
            content="[2026-01-10 | journal] Superconducting quantum devices and magnetic flux calculations.",
            chunk_metadata={"source_type": "journal"},
            embedding=_make_unit_vector(0),  # Close to query vector (dim 0)
        )
        session.add(c1)
        created_ids["vector_close"] = n1.id

        # Note 2: Exact term match for keyword "entanglement", but orthogonal embedding (dim 50)
        n2 = Note(
            ts=datetime.datetime(2026, 1, 20, 10, 0, tzinfo=datetime.UTC),
            note_date=datetime.date(2026, 1, 20),
            source_type="reading_note",
            content="Exploration of quantum entanglement properties and Bell inequalities.",
            content_hash="hash_note_2",
        )
        session.add(n2)
        session.flush()
        c2 = NoteChunk(
            note_id=n2.id,
            chunk_idx=0,
            content="[2026-01-20 | reading_note] Exploration of quantum entanglement properties and Bell inequalities.",
            chunk_metadata={"source_type": "reading_note"},
            embedding=_make_unit_vector(50),  # Orthogonal to query
        )
        session.add(c2)
        created_ids["term_match"] = n2.id

        # Note 3: Irrelevant note (orthogonal embedding dim 100, no quantum/entanglement text)
        n3 = Note(
            ts=datetime.datetime(2026, 2, 1, 10, 0, tzinfo=datetime.UTC),
            note_date=datetime.date(2026, 2, 1),
            source_type="journal",
            content="Completed routine chores and grocery shopping in the afternoon.",
            content_hash="hash_note_3",
        )
        session.add(n3)
        session.flush()
        c3 = NoteChunk(
            note_id=n3.id,
            chunk_idx=0,
            content="[2026-02-01 | journal] Completed routine chores and grocery shopping in the afternoon.",
            chunk_metadata={"source_type": "journal"},
            embedding=_make_unit_vector(100),
        )
        session.add(c3)
        created_ids["irrelevant"] = n3.id

        session.commit()

    return created_ids


def test_hybrid_search_fusion_differs_and_includes_single_leg_winner(seeded_search_notes: dict[str, int]):
    """Demonstrate that fused results differ from either leg alone and include single-leg winners."""
    # Custom embed function returning vector at dim 0
    def mock_embed(texts: list[str]) -> list[list[float]]:
        return [_make_unit_vector(0) for _ in texts]

    # Search for "entanglement" with top_k=2
    hits = hybrid_search(
        query="entanglement",
        top_k=2,
        embed_fn=mock_embed,
    )

    hit_note_ids = [h.note_id for h in hits]

    # Fused result must contain both the term winner (n2) and vector winner (n1)
    assert hit_note_ids == [
        seeded_search_notes["term_match"],
        seeded_search_notes["vector_close"],
    ]
    # Irrelevant note (n3) is excluded from top 2
    assert seeded_search_notes["irrelevant"] not in hit_note_ids


def test_hybrid_search_date_filters(seeded_search_notes: dict[str, int]):
    hits_jan15 = hybrid_search(
        query="quantum",
        date_from=datetime.date(2026, 1, 15),
    )
    hit_ids = [h.note_id for h in hits_jan15]
    # Note 1 is dated 2026-01-10 -> excluded by date_from 2026-01-15
    assert seeded_search_notes["vector_close"] not in hit_ids
    # Note 2 is dated 2026-01-20 -> included
    assert seeded_search_notes["term_match"] in hit_ids


def test_hybrid_search_source_type_filter(seeded_search_notes: dict[str, int]):
    hits_reading = hybrid_search(
        query="quantum",
        source_type="reading_note",
    )
    hit_ids = [h.note_id for h in hits_reading]
    # Note 2 is reading_note -> included
    assert seeded_search_notes["term_match"] in hit_ids
    # Note 1 is journal -> excluded
    assert seeded_search_notes["vector_close"] not in hit_ids


def test_api_search_unauthenticated():
    client = TestClient(app)
    resp = client.post("/v1/search", json={"query": "quantum"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_api_search_validation_errors():
    client = TestClient(app)
    # query too short (min length 2)
    resp = client.post(
        "/v1/search",
        headers={"X-API-Key": "test-key"},
        json={"query": "a"},
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "validation_error"

    # top_k too large (max 20)
    resp2 = client.post(
        "/v1/search",
        headers={"X-API-Key": "test-key"},
        json={"query": "valid query", "top_k": 25},
    )
    assert resp2.status_code == 422
    assert resp2.json()["error"]["code"] == "validation_error"


def test_api_search_success_with_schema(seeded_search_notes: dict[str, int]):
    client = TestClient(app)
    resp = client.post(
        "/v1/search",
        headers={"X-API-Key": "test-key"},
        json={"query": "quantum devices", "top_k": 5},
    )
    assert resp.status_code == 200
    hits = resp.json()
    assert isinstance(hits, list)
    if hits:
        hit = hits[0]
        assert "note_id" in hit
        assert "note_date" in hit
        assert "source_type" in hit
        assert "snippet" in hit
        assert "score" in hit
