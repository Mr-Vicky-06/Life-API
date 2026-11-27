"""Idempotent database loaders using ON CONFLICT upsert."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import literal_column
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ingestion.cleaning import clean_text, compute_content_hash
from app.models.commits import GithubCommit
from app.models.health import HealthDaily
from app.models.notes import Note, NoteChunk
from app.models.reading import ReadingLog
from app.models.screen_time import ScreenTime
from app.rag.chunking import chunk_note_content
from app.schemas.ingest import IngestResult

logger = logging.getLogger(__name__)


def upsert_health_daily(session: Session, rows: list[dict[str, Any]]) -> IngestResult:
    """Idempotently upsert health_daily rows."""
    if not rows:
        return IngestResult(source="health", inserted=0, updated=0, skipped=0)

    inserted = 0
    updated = 0

    for row in rows:
        stmt = (
            insert(HealthDaily)
            .values(**row)
            .on_conflict_do_update(
                index_elements=["date"],
                set_={
                    "sleep_hours": row.get("sleep_hours"),
                    "sleep_score": row.get("sleep_score"),
                    "deep_sleep_min": row.get("deep_sleep_min"),
                    "hrv_ms": row.get("hrv_ms"),
                    "resting_hr": row.get("resting_hr"),
                    "steps": row.get("steps"),
                    "source": row.get("source", "csv"),
                },
            )
            .returning(literal_column("xmax = 0").label("is_inserted"))
        )
        is_inserted = session.execute(stmt).scalar_one()
        if is_inserted:
            inserted += 1
        else:
            updated += 1

    session.flush()
    return IngestResult(source="health", inserted=inserted, updated=updated, skipped=0)


def upsert_reading_log(session: Session, rows: list[dict[str, Any]]) -> IngestResult:
    """Idempotently upsert reading_log rows."""
    if not rows:
        return IngestResult(source="reading", inserted=0, updated=0, skipped=0)

    inserted = 0
    updated = 0

    for row in rows:
        stmt = (
            insert(ReadingLog)
            .values(**row)
            .on_conflict_do_update(
                index_elements=["date", "title"],
                set_={
                    "pages_read": row.get("pages_read", 0),
                    "minutes": row["minutes"] if "minutes" in row else 0,
                },
            )
            .returning(literal_column("xmax = 0").label("is_inserted"))
        )
        is_inserted = session.execute(stmt).scalar_one()
        if is_inserted:
            inserted += 1
        else:
            updated += 1

    session.flush()
    return IngestResult(source="reading", inserted=inserted, updated=updated, skipped=0)


def upsert_screen_time(session: Session, rows: list[dict[str, Any]]) -> IngestResult:
    """Idempotently upsert screen_time rows."""
    if not rows:
        return IngestResult(source="screen_time", inserted=0, updated=0, skipped=0)

    inserted = 0
    updated = 0

    for row in rows:
        stmt = (
            insert(ScreenTime)
            .values(**row)
            .on_conflict_do_update(
                index_elements=["date", "category"],
                set_={"minutes": row.get("minutes", 0)},
            )
            .returning(literal_column("xmax = 0").label("is_inserted"))
        )
        is_inserted = session.execute(stmt).scalar_one()
        if is_inserted:
            inserted += 1
        else:
            updated += 1

    session.flush()
    return IngestResult(source="screen_time", inserted=inserted, updated=updated, skipped=0)


def upsert_github_commits(session: Session, rows: list[dict[str, Any]]) -> IngestResult:
    """Idempotently upsert github_commits rows."""
    if not rows:
        return IngestResult(source="github", inserted=0, updated=0, skipped=0)

    inserted = 0
    updated = 0

    for row in rows:
        stmt = (
            insert(GithubCommit)
            .values(**row)
            .on_conflict_do_update(
                index_elements=["sha"],
                set_={
                    "repo": row.get("repo"),
                    "committed_at": row.get("committed_at"),
                    "commit_date": row.get("commit_date"),
                    "message": row.get("message"),
                    "additions": row.get("additions", 0),
                    "deletions": row.get("deletions", 0),
                },
            )
            .returning(literal_column("xmax = 0").label("is_inserted"))
        )
        is_inserted = session.execute(stmt).scalar_one()
        if is_inserted:
            inserted += 1
        else:
            updated += 1

    session.flush()
    return IngestResult(source="github", inserted=inserted, updated=updated, skipped=0)


def upsert_notes(
    session: Session,
    rows: list[dict[str, Any]],
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
) -> IngestResult:
    """Idempotently insert notes and their chunk embeddings, deduping by content_hash."""
    if not rows:
        return IngestResult(source="notes", inserted=0, updated=0, skipped=0)

    inserted = 0
    skipped = 0

    for row in rows:
        raw_content = row["content"]
        cleaned_content = clean_text(raw_content)
        note_date = row["note_date"]
        source_type = row["source_type"]
        content_hash = compute_content_hash(f"{note_date}|{source_type}|{cleaned_content}")

        stmt = (
            insert(Note)
            .values(
                ts=row["ts"],
                note_date=note_date,
                source_type=source_type,
                content=cleaned_content,
                content_hash=content_hash,
            )
            .on_conflict_do_nothing(index_elements=["content_hash"])
            .returning(Note.id)
        )
        note_id = session.execute(stmt).scalar_one_or_none()
        if note_id is None:
            skipped += 1
            continue

        inserted += 1
        # Chunk note content
        chunks = chunk_note_content(cleaned_content, note_date, source_type)
        if not chunks:
            continue

        # Generate embeddings for header-prepended chunks
        chunk_texts = [c[1] for c in chunks]
        if embed_fn is not None:
            embeddings = embed_fn(chunk_texts)
        else:
            from app.rag.embeddings import embed_texts
            embeddings = embed_texts(chunk_texts)

        for (idx, header_content, _raw), emb in zip(chunks, embeddings, strict=True):
            chunk_obj = NoteChunk(
                note_id=note_id,
                chunk_idx=idx,
                content=header_content,
                chunk_metadata={"source_type": source_type, "note_date": str(note_date)},
                embedding=emb,
            )
            session.add(chunk_obj)

    session.flush()
    return IngestResult(source="notes", inserted=inserted, updated=0, skipped=skipped)
