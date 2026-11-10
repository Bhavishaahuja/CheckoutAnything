# The four tables from the build brief, plus the two the merchant's review of a catalog needs.

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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


class ItemReview(Base):
    # what the merchant decided about one item, kept apart from the spec (which only Claude and
    # merchant edits write). one row per item, made when the connect run ends
    __tablename__ = "item_reviews"
    __table_args__ = (UniqueConstraint("store_id", "item_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    item_id: Mapped[str] = mapped_column(String(60))
    # where the item sits in the catalog an agent reads, 0 first
    position: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # None means stock isn't tracked. a number is how many are left
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # only published items can be bought. clean verified items start published, items with a
    # field the agent was unsure about wait for the merchant
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    # JSON: flagged field -> how the merchant settled it. {"by": "confirm"}, or
    # {"by": "edit", "was": "7.00"} with the value the agent had, so putting that value back
    # (an undo) brings the flag back
    resolved_fields: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ColumnLabel(Base):
    # a catalog column the merchant renamed, "Price" -> "Cost"
    __tablename__ = "column_labels"
    __table_args__ = (UniqueConstraint("store_id", "field"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    field: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(40))
