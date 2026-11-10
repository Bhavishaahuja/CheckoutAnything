# The four tables from the build brief.

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db import Base

# store status
CONNECTING = "connecting"
LIVE = "live"
FAILED = "failed"


def utc_now():
    return datetime.now(timezone.utc)


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_url: Mapped[str] = mapped_column(String(2048))
    merchant_name: Mapped[str] = mapped_column(String(200), default="")
    # connecting -> live (at least 1 item verified) or failed
    status: Mapped[str] = mapped_column(String(20), default=CONNECTING)
    # "live" or "replay", which way this store was connected
    mode: Mapped[str] = mapped_column(String(20), default="live")
    # why it failed, when it did
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StoreSpecRow(Base):
    # every version is kept, so the repair history stays visible
    __tablename__ = "store_specs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    spec_json: Mapped[str] = mapped_column(Text)
    # what changed in this version, "First extraction" or the repair note
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class VerificationRun(Base):
    # one row per attempt at one item
    __tablename__ = "verification_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    item_id: Mapped[str] = mapped_column(String(60))
    # 0 is the first try, 1 to 3 are the tries after a repair
    attempt: Mapped[int] = mapped_column(Integer)
    spec_version: Mapped[int] = mapped_column(Integer)
    page_check_ok: Mapped[bool] = mapped_column(Boolean)
    # None when the page check failed, the PayPal check never ran
    paypal_check_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    paypal_order_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    item_id: Mapped[str] = mapped_column(String(60))
    variant_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # comma separated add-on ids
    add_on_ids: Mapped[str] = mapped_column(String(600), default="")
    # the line as PayPal saw it, "Sourdough Loaf (Half loaf) + Sliced"
    description: Mapped[str] = mapped_column(String(200), default="")
    quantity: Mapped[int] = mapped_column(Integer)
    # a "12.00" string, same as everywhere else. never a float
    total: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    paypal_order_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    capture_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # captured or failed
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "agent" or "manual"
    created_by: Mapped[str] = mapped_column(String(20), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
