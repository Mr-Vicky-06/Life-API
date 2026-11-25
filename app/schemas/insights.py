"""Pydantic schema for GET /v1/insights/daily endpoint."""
from __future__ import annotations

import datetime

from pydantic import BaseModel, Field


class DailyInsight(BaseModel):
    timestamp: datetime.date
    summary: str = Field(max_length=300)
    metrics: dict[str, float | int]
    insights: str = Field(max_length=400)
