"""Initial migration: pgvector, tables, indexes, views, and life_ro role grants.

Revision ID: 0001_init
Revises:
Create Date: 2026-11-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001_init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Vector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 2. Ensure life_ro role exists
    op.execute("""
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'life_ro') THEN
    CREATE ROLE life_ro WITH LOGIN PASSWORD 'life_ro' NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END
$$;
""")
    op.execute("GRANT USAGE ON SCHEMA public TO life_ro;")

    # 3. Create tables
    op.create_table(
        "health_daily",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("sleep_hours", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("sleep_score", sa.Integer(), nullable=True),
        sa.Column("deep_sleep_min", sa.Integer(), nullable=True),
        sa.Column("hrv_ms", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("resting_hr", sa.Integer(), nullable=True),
        sa.Column("steps", sa.Integer(), nullable=True),
        sa.Column("source", sa.Text(), server_default=sa.text("'csv'"), nullable=False),
        sa.PrimaryKeyConstraint("date"),
    )

    op.create_table(
        "github_commits",
        sa.Column("sha", sa.Text(), nullable=False),
        sa.Column("repo", sa.Text(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("commit_date", sa.Date(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("additions", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("deletions", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("sha"),
    )

    op.create_table(
        "reading_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("pages_read", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("minutes", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", "title", name="uq_reading_log_date_title"),
    )

    op.create_table(
        "screen_time",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("date", "category"),
    )

    op.create_table(
        "notes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note_date", sa.Date(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('journal', 'reading_note', 'commit_message')",
            name="chk_notes_source_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_hash"),
    )

    op.create_table(
        "note_chunks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("note_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_idx", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", "chunk_idx", name="uq_note_chunks_note_id_chunk_idx"),
    )

    # 4. Indexes
    op.create_index("note_chunks_tsv_idx", "note_chunks", ["tsv"], postgresql_using="gin")
    op.execute(
        "CREATE INDEX note_chunks_emb_idx ON note_chunks USING hnsw (embedding vector_cosine_ops);"
    )

    op.create_table(
        "query_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("endpoint", sa.Text(), nullable=True),
        sa.Column("question_masked", sa.Text(), nullable=True),
        sa.Column("sql", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # 5. Allowlisted Views
    op.execute("""
CREATE VIEW v_daily_summary AS
SELECT h.date, h.sleep_hours, h.sleep_score, h.deep_sleep_min, h.hrv_ms, h.resting_hr, h.steps,
       COALESCE(c.commits,0) AS commits, COALESCE(c.lines_added,0) AS lines_added,
       COALESCE(r.pages_read,0) AS pages_read, COALESCE(r.reading_minutes,0) AS reading_minutes,
       COALESCE(s.screen_minutes,0) AS screen_minutes
FROM health_daily h
LEFT JOIN (SELECT commit_date AS date, count(*) commits, sum(additions) lines_added
           FROM github_commits GROUP BY 1) c USING (date)
LEFT JOIN (SELECT date, sum(pages_read) pages_read, sum(minutes) reading_minutes
           FROM reading_log GROUP BY 1) r USING (date)
LEFT JOIN (SELECT date, sum(minutes) screen_minutes FROM screen_time GROUP BY 1) s USING (date);
""")

    op.execute(
        "CREATE VIEW v_commits AS "
        "SELECT sha, repo, committed_at, commit_date, additions, deletions FROM github_commits;"
    )
    op.execute("CREATE VIEW v_screen_time AS SELECT date, category, minutes FROM screen_time;")
    op.execute("CREATE VIEW v_reading AS SELECT date, title, pages_read, minutes FROM reading_log;")

    # 6. Permissions for life_ro
    op.execute(
        "GRANT SELECT ON v_daily_summary, v_commits, v_screen_time, v_reading TO life_ro;"
    )


def downgrade() -> None:
    # Revoke permissions and drop views
    op.execute(
        "REVOKE SELECT ON v_daily_summary, v_commits, v_screen_time, v_reading FROM life_ro;"
    )
    op.execute("DROP VIEW IF EXISTS v_reading;")
    op.execute("DROP VIEW IF EXISTS v_screen_time;")
    op.execute("DROP VIEW IF EXISTS v_commits;")
    op.execute("DROP VIEW IF EXISTS v_daily_summary;")

    # Drop tables in reverse dependency order
    op.drop_table("query_log")
    op.drop_index("note_chunks_emb_idx", table_name="note_chunks")
    op.drop_index("note_chunks_tsv_idx", table_name="note_chunks", postgresql_using="gin")
    op.drop_table("note_chunks")
    op.drop_table("notes")
    op.drop_table("screen_time")
    op.drop_table("reading_log")
    op.drop_table("github_commits")
    op.drop_table("health_daily")

    # Extension
    op.execute("DROP EXTENSION IF EXISTS vector CASCADE;")
