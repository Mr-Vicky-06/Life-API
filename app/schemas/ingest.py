"""Schemas for ingestion requests, responses, and CSV row validation."""
from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel, Field


class IngestResult(BaseModel):
    source: str
    inserted: int
    updated: int
    skipped: int
    errors: list[str] = []


class GithubIngestRequest(BaseModel):
    days: int = Field(default=30, ge=1, le=365)


class NoteItem(BaseModel):
    ts: str | datetime.datetime
    source_type: Literal["journal", "reading_note", "commit_message"]
    content: str = Field(min_length=1)


class HealthCSVRow(BaseModel):
    date: datetime.date
    sleep_hours: float | None = None
    sleep_score: int | None = None
    deep_sleep_min: int | None = None
    hrv_ms: float | None = None
    resting_hr: int | None = None
    steps: int | None = None
    source: str = "csv"


class ReadingCSVRow(BaseModel):
    date: datetime.date
    title: str = Field(min_length=1)
    pages_read: int = 0
    minutes: int | None = 0


class ScreenTimeCSVRow(BaseModel):
    date: datetime.date
    category: str = Field(min_length=1)
    minutes: int = Field(ge=0)
