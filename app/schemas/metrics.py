"""Pydantic schema for GET /v1/metrics endpoint."""
from __future__ import annotations

import datetime

from pydantic import BaseModel


class MetricsResponse(BaseModel):
    from_date: datetime.date
    to_date: datetime.date
    rows: list[dict[str, float | int | str | None]]
