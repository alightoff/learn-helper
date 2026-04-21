"""add study session state

Revision ID: a4d2d9db3e3f
Revises: 5fc366a3fb08
Create Date: 2026-04-21 17:05:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "a4d2d9db3e3f"
down_revision = "5fc366a3fb08"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column(
        "study_sessions",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="completed"),
    )
    op.add_column(
        "study_sessions",
        sa.Column("active_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_study_sessions_status"), "study_sessions", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_study_sessions_status"), table_name="study_sessions")
    op.drop_column("study_sessions", "active_started_at")
    op.drop_column("study_sessions", "status")
