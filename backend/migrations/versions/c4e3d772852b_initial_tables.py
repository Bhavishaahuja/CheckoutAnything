"""initial tables: mandates, orders, decisions, approvals

Revision ID: c4e3d772852b
Revises:
Create Date: 2026-10-21 21:18:12.617767

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4e3d772852b"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def string_enum(name, *values):
    # same as models.string_enum: a VARCHAR plus a CHECK constraint, not a Postgres enum.
    # the Enum creates its own CHECK, so don't add a separate CheckConstraint too
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=20)


def upgrade() -> None:
    op.create_table(
        "mandates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("buyer_label", sa.String(length=200), nullable=False),
        sa.Column("raw_request", sa.Text(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("max_price", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("merchant", sa.String(length=200), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mandate_id", sa.Integer(), nullable=False),
        sa.Column("paypal_order_id", sa.String(length=64), nullable=True),
        sa.Column("authorization_id", sa.String(length=64), nullable=True),
        sa.Column("capture_id", sa.String(length=64), nullable=True),
        sa.Column("vault_id", sa.String(length=64), nullable=True),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("total", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "status",
            string_enum("order_status", "created", "authorized", "captured", "voided", "failed"),
            nullable=False,
        ),
        sa.Column("authorization_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["mandate_id"], ["mandates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("paypal_order_id"),
    )
    op.create_index(op.f("ix_orders_authorization_id"), "orders", ["authorization_id"])
    op.create_index(op.f("ix_orders_capture_id"), "orders", ["capture_id"])
    op.create_index(op.f("ix_orders_mandate_id"), "orders", ["mandate_id"])

    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("verdict", string_enum("verdict", "match", "mismatch", "unsure"), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("checked_by", string_enum("checked_by", "rules", "claude"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_decisions_order_id"), "decisions", ["order_id"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("action", string_enum("approval_action", "approve", "reject"), nullable=True),
        sa.Column("decided_by", sa.String(length=200), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_approvals_order_id"), "approvals", ["order_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_approvals_order_id"), table_name="approvals")
    op.drop_table("approvals")
    op.drop_index(op.f("ix_decisions_order_id"), table_name="decisions")
    op.drop_table("decisions")
    op.drop_index(op.f("ix_orders_mandate_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_capture_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_authorization_id"), table_name="orders")
    op.drop_table("orders")
    op.drop_table("mandates")
