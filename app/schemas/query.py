"""Pydantic schemas for Text-to-SQL query endpoint."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    history: list[str] = Field(default_factory=list, max_length=4)


class QueryResponse(BaseModel):
    question: str
    standalone_question: str
    sql: str
    explanation: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    summary: str
    model: str
    latency_ms: int
