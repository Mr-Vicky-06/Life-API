"""Make reading_log.minutes nullable so unmeasured sources store NULL.

Revision ID: 0002_nullable_reading_minutes
Revises: 0001_init
Create Date: 2026-11-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_nullable_reading_minutes"
down_revision: str | None = "0001_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "reading_log",
        "minutes",
        existing_type=sa.Integer(),
        nullable=True,
        server_default=None,
    )


def downgrade() -> None:
    op.execute("UPDATE reading_log SET minutes = 0 WHERE minutes IS NULL;")
    op.alter_column(
        "reading_log",
        "minutes",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    )
