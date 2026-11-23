"""Ingestion API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.deps import get_rw_session, verify_api_key
from app.ingestion.cleaning import clean_text, parse_timestamp
from app.ingestion.csv_import import (
    parse_health_csv,
    parse_reading_csv,
    parse_screen_time_csv,
)
from app.ingestion.github import sync_github_commits
from app.ingestion.loaders import (
    upsert_health_daily,
    upsert_notes,
    upsert_reading_log,
    upsert_screen_time,
)
from app.schemas.ingest import GithubIngestRequest, IngestResult, NoteItem

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.post("/github", response_model=IngestResult)
def ingest_github(
    payload: GithubIngestRequest = GithubIngestRequest(),
    session: Session = Depends(get_rw_session),
) -> IngestResult:
    """Pull and synchronize GitHub commits."""
    return sync_github_commits(session, days=payload.days)


@router.post("/health", response_model=IngestResult)
async def ingest_health(
    file: UploadFile = File(...),
    session: Session = Depends(get_rw_session),
) -> IngestResult:
    """Ingest daily health metrics from CSV file."""
    content_bytes = await file.read()
    csv_text = content_bytes.decode("utf-8-sig")
    rows, errors = parse_health_csv(csv_text)
    result = upsert_health_daily(session, rows)
    result.errors.extend(errors)
    return result


@router.post("/reading", response_model=IngestResult)
async def ingest_reading(
    file: UploadFile = File(...),
    session: Session = Depends(get_rw_session),
) -> IngestResult:
    """Ingest reading logs from CSV file."""
    content_bytes = await file.read()
    csv_text = content_bytes.decode("utf-8-sig")
    rows, errors = parse_reading_csv(csv_text)
    result = upsert_reading_log(session, rows)
    result.errors.extend(errors)
    return result


@router.post("/screen_time", response_model=IngestResult)
async def ingest_screen_time(
    file: UploadFile = File(...),
    session: Session = Depends(get_rw_session),
) -> IngestResult:
    """Ingest screen time records from CSV file."""
    content_bytes = await file.read()
    csv_text = content_bytes.decode("utf-8-sig")
    rows, errors = parse_screen_time_csv(csv_text)
    result = upsert_screen_time(session, rows)
    result.errors.extend(errors)
    return result


@router.post("/notes", response_model=IngestResult)
def ingest_notes(
    notes: list[NoteItem],
    session: Session = Depends(get_rw_session),
) -> IngestResult:
    """Ingest notes and generate vector embeddings for chunks."""
    note_rows = []
    for item in notes:
        ts = parse_timestamp(item.ts)
        cleaned = clean_text(item.content)
        note_rows.append({
            "ts": ts,
            "note_date": ts.date(),
            "source_type": item.source_type,
            "content": cleaned,
        })
    return upsert_notes(session, note_rows)
