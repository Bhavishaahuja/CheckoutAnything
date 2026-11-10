"""add check result to decisions, rename checked_by claude to ai

Revision ID: f2b8c61a7d30
Revises: e7a1d4c09b52
Create Date: 2026-11-04 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2b8c61a7d30"
down_revision: Union[str, Sequence[str], None] = "e7a1d4c09b52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def replace_checked_by_value(old_value, new_value, allowed_values):
    # the constraint has to come off first, since the update breaks the old one and the old
    # rows break the new one. batch mode because SQLite can't alter constraints in place,
    # on Postgres it's a plain ALTER TABLE
    with op.batch_alter_table("decisions") as batch_op:
        batch_op.drop_constraint("checked_by", type_="check")

    op.execute(
        "UPDATE decisions SET checked_by = '" + new_value + "' "
        "WHERE checked_by = '" + old_value + "'"
    )

    with op.batch_alter_table("decisions") as batch_op:
        batch_op.create_check_constraint("checked_by", "checked_by IN " + allowed_values)


def upgrade() -> None:
    # all nullable with no backfill: rows from before this have no such data
    with op.batch_alter_table("decisions") as batch_op:
        batch_op.add_column(sa.Column("mismatched_fields", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("rule_results", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("latency_ms", sa.Integer(), nullable=True))

    replace_checked_by_value("claude", "ai", "('rules', 'ai')")


def downgrade() -> None:
    replace_checked_by_value("ai", "claude", "('rules', 'claude')")

    with op.batch_alter_table("decisions") as batch_op:
        batch_op.drop_column("latency_ms")
        batch_op.drop_column("rule_results")
        batch_op.drop_column("mismatched_fields")
