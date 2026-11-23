"""ORM model for reading log."""
from __future__ import annotations

import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ReadingLog(Base):
    __tablename__ = "reading_log"

    id: Mapped[int] = mapped_column(
        sa.BigInteger, primary_key=True, autoincrement=True
    )
    date: Mapped[datetime.date] = mapped_column(sa.Date, nullable=False)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    pages_read: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    minutes: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )

    __table_args__ = (
        sa.UniqueConstraint("date", "title", name="uq_reading_log_date_title"),
    )
