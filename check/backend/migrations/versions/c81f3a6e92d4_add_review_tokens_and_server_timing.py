"""add review token columns to orders, client_decision_ms to approvals

Revision ID: c81f3a6e92d4
Revises: a9d47e2c15b8
Create Date: 2026-11-05 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c81f3a6e92d4"
down_revision: Union[str, Sequence[str], None] = "a9d47e2c15b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(sa.Column("review_token_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("review_token_used_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_unique_constraint("uq_orders_review_token_hash", ["review_token_hash"])

    with op.batch_alter_table("approvals") as batch_op:
        batch_op.add_column(sa.Column("client_decision_ms", sa.Integer(), nullable=True))

    # every decision_ms saved so far came from the client, and from here on that column means the
    # server's number. move them over so an old value can't pass as a measured one
    op.execute("UPDATE approvals SET client_decision_ms = decision_ms, decision_ms = NULL")


def downgrade() -> None:
    op.execute("UPDATE approvals SET decision_ms = client_decision_ms")

    with op.batch_alter_table("approvals") as batch_op:
        batch_op.drop_column("client_decision_ms")

    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_constraint("uq_orders_review_token_hash", type_="unique")
        batch_op.drop_column("review_token_used_at")
        batch_op.drop_column("review_token_hash")
