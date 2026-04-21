"""add study session scope and target cycles

Revision ID: cc0f13d37b9a
Revises: a4d2d9db3e3f
Create Date: 2026-04-21 19:20:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "cc0f13d37b9a"
down_revision = "a4d2d9db3e3f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("study_sessions") as batch_op:
        batch_op.add_column(sa.Column("outline_item_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("target_cycles", sa.Integer(), nullable=True))
        batch_op.create_index(op.f("ix_study_sessions_outline_item_id"), ["outline_item_id"], unique=False)
        batch_op.create_foreign_key(
            op.f("fk_study_sessions_outline_item_id_resource_outline_items"),
            "resource_outline_items",
            ["outline_item_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("study_sessions") as batch_op:
        batch_op.drop_constraint(
            op.f("fk_study_sessions_outline_item_id_resource_outline_items"),
            type_="foreignkey",
        )
        batch_op.drop_index(op.f("ix_study_sessions_outline_item_id"))
        batch_op.drop_column("target_cycles")
        batch_op.drop_column("outline_item_id")
