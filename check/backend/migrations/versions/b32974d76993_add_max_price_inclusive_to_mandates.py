"""add max_price_inclusive to mandates

Revision ID: b32974d76993
Revises: c4e3d772852b
Create Date: 2026-10-21 21:38:11.872921

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b32974d76993"
down_revision: Union[str, Sequence[str], None] = "c4e3d772852b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default true so any mandates saved before this column existed read as
    # "up to max_price", same as the app default
    op.add_column(
        "mandates",
        sa.Column(
            "max_price_inclusive", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("mandates", "max_price_inclusive")
