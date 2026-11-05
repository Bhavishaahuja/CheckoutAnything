# the four tables Leash needs for week 1. field choices follow spikes/README.md

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base


class OrderStatus(str, enum.Enum):
    created = "created"
    authorized = "authorized"
    captured = "captured"
    voided = "voided"
    failed = "failed"


class Verdict(str, enum.Enum):
    match = "match"
    mismatch = "mismatch"
    unsure = "unsure"


class CheckedBy(str, enum.Enum):
    rules = "rules"
    ai = "ai"


class ApprovalAction(str, enum.Enum):
    approve = "approve"
    reject = "reject"


def string_enum(enum_class, name):
    # store enums as plain strings with a CHECK constraint instead of a Postgres enum
    # type, so adding a value later is a simple migration
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda members: [member.value for member in members],
    )


def created_at_column():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Mandate(Base):
    # what the human told their agent it's allowed to buy
    __tablename__ = "mandates"

    id: Mapped[int] = mapped_column(primary_key=True)
    buyer_label: Mapped[str] = mapped_column(String(200))
    # the human's own words, kept verbatim for dispute evidence
    raw_request: Mapped[str] = mapped_column(Text)
    # structured version Claude/the rules check against (categories, limits, etc)
    rules: Mapped[dict] = mapped_column(JSON)
    max_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # True: total may equal max_price ("up to $120"). False: must be below it ("under $120")
    max_price_inclusive: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true()
    )
    merchant: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()

    orders: Mapped[list["Order"]] = relationship(back_populates="mandate")


class Order(Base):
    # one agent order and where its PayPal money is at
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    mandate_id: Mapped[int] = mapped_column(ForeignKey("mandates.id"), index=True)
    paypal_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    authorization_id: Mapped[str | None] = mapped_column(String(64), index=True)
    # disputes point at this (disputed_transactions[].seller_transaction_id), see spike 3
    capture_id: Mapped[str | None] = mapped_column(String(64), index=True)
    vault_id: Mapped[str | None] = mapped_column(String(64))
    items: Mapped[list] = mapped_column(JSON)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # the part of total that's shipping. null on orders saved before this column existed,
    # we don't know their split and 0 would be a made-up number
    shipping_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[OrderStatus] = mapped_column(
        string_enum(OrderStatus, "order_status"), default=OrderStatus.created
    )
    # PayPal authorizations last 29 days (spike 2), the human has to decide before this
    authorization_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()

    mandate: Mapped[Mandate] = relationship(back_populates="orders")
    # oldest first. the database doesn't promise any order unless it's asked for one
    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="order", order_by="Decision.id"
    )
    approvals: Mapped[list["Approval"]] = relationship(back_populates="order")

    @property
    def intent_check(self):
        # the newest check result, or None if the order hasn't been checked. reads the saved row
        # so API responses always show what's actually in the database
        if not self.decisions:
            return None
        return self.decisions[-1]


class Decision(Base):
    # the mandate check result for an order
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    verdict: Mapped[Verdict] = mapped_column(string_enum(Verdict, "verdict"))
    # 0 to 100, higher means more likely the human didn't want this
    risk_score: Mapped[int | None] = mapped_column(Integer)
    # the one-line reason the human sees
    reason: Mapped[str] = mapped_column(Text)
    # what differs: rule names when the rules caught it, otherwise what Claude listed.
    # these three are null on rows saved before the check was wired in
    mismatched_fields: Mapped[list | None] = mapped_column(JSON)
    # every hard rule's result as {rule, passed, reason}, including the ones that passed
    rule_results: Mapped[list | None] = mapped_column(JSON)
    # how long the whole check took
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    checked_by: Mapped[CheckedBy] = mapped_column(string_enum(CheckedBy, "checked_by"))
    created_at: Mapped[datetime] = created_at_column()

    order: Mapped[Order] = relationship(back_populates="decisions")


class Approval(Base):
    # the human looking at a flagged order. timing feeds the rubber-stamp watch
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    # empty until the human actually taps approve or reject
    action: Mapped[ApprovalAction | None] = mapped_column(
        string_enum(ApprovalAction, "approval_action")
    )
    decided_by: Mapped[str | None] = mapped_column(String(200))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # decided_at minus opened_at, stored so the dashboard doesn't recompute it
    decision_ms: Mapped[int | None] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="approvals")
