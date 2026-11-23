"""ORM model for query logs."""
from __future__ import annotations

import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class QueryLog(Base):
    __tablename__ = "query_log"

    id: Mapped[int] = mapped_column(
        sa.BigInteger, primary_key=True, autoincrement=True
    )
    ts: Mapped[datetime.datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")
    )
    endpoint: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    question_masked: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    sql: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    ok: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
