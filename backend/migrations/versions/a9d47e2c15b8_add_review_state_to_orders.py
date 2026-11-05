"""add review_state, void_result and payment_claimed_at to orders

Revision ID: a9d47e2c15b8
Revises: f2b8c61a7d30
Create Date: 2026-11-05 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9d47e2c15b8"
down_revision: Union[str, Sequence[str], None] = "f2b8c61a7d30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(sa.Column("review_state", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("void_result", sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column("payment_claimed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_check_constraint(
            "review_state",
            "review_state IN ('auto_approved', 'needs_review', 'approved', 'rejected')",
        )

    # holds already sitting there have to reach a human, approve and reject only work on
    # needs_review. orders already captured or voided stay null, we don't know who decided
    op.execute("UPDATE orders SET review_state = 'needs_review' WHERE status = 'authorized'")


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_constraint("review_state", type_="check")
        batch_op.drop_column("payment_claimed_at")
        batch_op.drop_column("void_result")
        batch_op.drop_column("review_state")
