"""add shipping_amount to orders

Revision ID: e7a1d4c09b52
Revises: b32974d76993
Create Date: 2026-11-04 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7a1d4c09b52"
down_revision: Union[str, Sequence[str], None] = "b32974d76993"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # nullable with no backfill: existing totals already include shipping and we never saved
    # how much, so those rows stay "unknown" instead of claiming $0.00
    op.add_column(
        "orders",
        sa.Column("shipping_amount", sa.Numeric(precision=10, scale=2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "shipping_amount")
