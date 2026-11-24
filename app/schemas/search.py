"""Pydantic schemas for search endpoint."""
from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    top_k: int = Field(default=8, ge=1, le=20)
    source_type: Literal["journal", "reading_note", "commit_message"] | None = None
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None


class SearchHit(BaseModel):
    note_id: int
    note_date: datetime.date
    source_type: str
    snippet: str
    score: float
