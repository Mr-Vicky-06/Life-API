"""ORM model for screen time logs."""
from __future__ import annotations

import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ScreenTime(Base):
    __tablename__ = "screen_time"

    date: Mapped[datetime.date] = mapped_column(sa.Date, primary_key=True)
    category: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    minutes: Mapped[int] = mapped_column(sa.Integer, nullable=False)
