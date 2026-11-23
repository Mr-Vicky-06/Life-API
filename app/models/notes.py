"""ORM models for notes and note chunks with vector embeddings."""
from __future__ import annotations

import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(
        sa.BigInteger, primary_key=True, autoincrement=True
    )
    ts: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    note_date: Mapped[datetime.date] = mapped_column(sa.Date, nullable=False)
    source_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)

    chunks: Mapped[list[NoteChunk]] = relationship(
        "NoteChunk", back_populates="note", cascade="all, delete-orphan"
    )

    __table_args__ = (
        sa.CheckConstraint(
            "source_type IN ('journal', 'reading_note', 'commit_message')",
            name="chk_notes_source_type",
        ),
    )


class NoteChunk(Base):
    __tablename__ = "note_chunks"

    id: Mapped[int] = mapped_column(
        sa.BigInteger, primary_key=True, autoincrement=True
    )
    note_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
    )
    chunk_idx: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        sa.Computed("to_tsvector('english', content)", persisted=True),
        nullable=True,
    )

    note: Mapped[Note] = relationship("Note", back_populates="chunks")

    __table_args__ = (
        sa.UniqueConstraint("note_id", "chunk_idx", name="uq_note_chunks_note_id_chunk_idx"),
        sa.Index("note_chunks_tsv_idx", "tsv", postgresql_using="gin"),
        sa.Index(
            "note_chunks_emb_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
