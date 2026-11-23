"""ORM model for daily health metrics."""
from __future__ import annotations

import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class HealthDaily(Base):
    __tablename__ = "health_daily"

    date: Mapped[datetime.date] = mapped_column(sa.Date, primary_key=True)
    sleep_hours: Mapped[Decimal | None] = mapped_column(sa.Numeric(4, 2), nullable=True)
    sleep_score: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    deep_sleep_min: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    hrv_ms: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 2), nullable=True)
    resting_hr: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    steps: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    source: Mapped[str] = mapped_column(
        sa.Text, nullable=False, server_default=sa.text("'csv'")
    )
