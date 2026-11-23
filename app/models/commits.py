"""ORM model for GitHub commits."""
from __future__ import annotations

import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GithubCommit(Base):
    __tablename__ = "github_commits"

    sha: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    repo: Mapped[str] = mapped_column(sa.Text, nullable=False)
    committed_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    commit_date: Mapped[datetime.date] = mapped_column(sa.Date, nullable=False)
    message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    additions: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    deletions: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
