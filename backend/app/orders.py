# Buying. The price is always worked out here from the verified spec, a price sent by the
# client is never read. Then: create the PayPal order paid with the saved sandbox buyer wallet
# (vault id), which captures in the same call, and record it.
#
# Price math, all in Decimal:
#   unit  = (variant price if a variant was picked, else the item price) + every add-on price
#   total = unit * quantity + flat shipping (once per order)

import uuid
from dataclasses import dataclass
from decimal import Decimal

from backend.app.models import Order
from backend.app.paypal_client import (
    PAYPAL_FAILURES,
    build_order_body,
    describe_failure,
    first_capture,
)
from backend.app.spec import MAX_NAME_LENGTH

MAX_QUANTITY = 100
CENT = Decimal("0.01")


class OrderError(Exception):
    # the request can't be priced or paid. status_code is what the API answers with
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Quote:
    item_id: str
    variant_id: str | None
    add_on_ids: list[str]
    line_name: str
    quantity: int
    unit_amount: Decimal
    item_total: Decimal
    shipping: Decimal
    total: Decimal
    currency: str


def price_order(spec, verified_item_ids, item_id, variant_id=None, add_on_ids=None,
                quantity=1):
    add_on_ids = add_on_ids or []

    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise OrderError("quantity has to be a whole number")
    if quantity < 1 or quantity > MAX_QUANTITY:
        raise OrderError("quantity has to be between 1 and " + str(MAX_QUANTITY))

    item = spec.find_item(item_id)
    if item is None:
        raise OrderError("This store has no item " + str(item_id), 404)
    if not item.available:
        raise OrderError(item.name + " isn't available")
    if item_id not in verified_item_ids:
        raise OrderError(item.name + " hasn't passed verification, so it can't be bought")

    unit = Decimal(item.unit_price)
    line_name = item.name

    if variant_id:
        chosen = None
        for variant in item.variants:
            if variant.id == variant_id:
                chosen = variant
                break
        if chosen is None:
            raise OrderError(item.name + " has no variant " + str(variant_id))
        # a variant's price is the whole price, not something added on
        unit = Decimal(chosen.unit_price)
        line_name += " (" + chosen.label + ")"

    seen = set()
    for add_on_id in add_on_ids:
        if add_on_id in seen:
            raise OrderError("Add-on " + str(add_on_id) + " is listed twice")
        seen.add(add_on_id)
        chosen = None
        for add_on in item.add_ons:
            if add_on.id == add_on_id:
                chosen = add_on
                break
        if chosen is None:
            raise OrderError(item.name + " has no add-on " + str(add_on_id))
        unit += Decimal(chosen.price)
        line_name += " + " + chosen.label

    shipping = Decimal("0.00")
    if spec.shipping.type == "flat":
        shipping = Decimal(spec.shipping.amount)

    item_total = (unit * quantity).quantize(CENT)
    return Quote(
        item_id=item.id,
        variant_id=variant_id or None,
        add_on_ids=list(add_on_ids),
        # PayPal cuts names off at 127 characters
        line_name=line_name[:MAX_NAME_LENGTH],
        quantity=quantity,
        unit_amount=unit.quantize(CENT),
        item_total=item_total,
        shipping=shipping.quantize(CENT),
        total=(item_total + shipping).quantize(CENT),
        currency=spec.merchant.currency,
    )


def place_order(session, paypal, vault_id, store, quote, created_by="manual"):
    # pays for a priced order with the saved wallet and saves the Order row either way.
    # returns the Order. a failed payment comes back with status "failed" and the reason
    if not vault_id:
        raise OrderError(
            "BUYER_VAULT_ID isn't set on the API, so there's no saved wallet to pay with", 503
        )

    order = Order(
        store_id=store.id,
        item_id=quote.item_id,
        variant_id=quote.variant_id,
        add_on_ids=",".join(quote.add_on_ids),
        description=quote.line_name,
        quantity=quote.quantity,
        total=str(quote.total),
        currency=quote.currency,
        status="failed",
        created_by=created_by,
    )

    body = build_order_body(
        currency=quote.currency,
        item_name=quote.line_name,
        unit_amount=quote.unit_amount,
        quantity=quote.quantity,
        shipping_amount=quote.shipping,
        custom_id="store-" + str(store.id) + "-" + quote.item_id,
        vault_id=vault_id,
    )
    # our own request id: required when the create call pays, and it makes this one order
    request_id = str(uuid.uuid4())

    try:
        paypal_order = paypal.create_order(body, request_id=request_id)
    except PAYPAL_FAILURES as error:
        order.error = describe_failure(error)
        session.add(order)
        session.commit()
        return order

    order.paypal_order_id = paypal_order.get("id")
    capture = first_capture(paypal_order)
    # COMPLETED alone isn't enough, PayPal says to check the capture's own status
    if capture is None:
        order.error = "PayPal took the order (" + str(paypal_order.get("status")) + \
            ") but didn't capture a payment"
    elif capture.get("status") != "COMPLETED":
        order.capture_id = capture.get("id")
        order.error = "PayPal's capture is " + str(capture.get("status")) + ", not COMPLETED"
    else:
        captured = (capture.get("amount") or {}).get("value")
        if captured is None or Decimal(str(captured)) != quote.total:
            order.capture_id = capture.get("id")
            order.error = "PayPal captured " + str(captured) + " but the order total is " + \
                str(quote.total)
        else:
            order.capture_id = capture.get("id")
            order.status = "captured"

    session.add(order)
    session.commit()
    return order


def order_to_dict(order, store_name=None):
    return {
        "id": order.id,
        "store_id": order.store_id,
        "store_name": store_name,
        "item_id": order.item_id,
        "variant_id": order.variant_id,
        "add_on_ids": [part for part in order.add_on_ids.split(",") if part],
        "description": order.description,
        "quantity": order.quantity,
        "total": order.total,
        "currency": order.currency,
        "paypal_order_id": order.paypal_order_id,
        "capture_id": order.capture_id,
        "status": order.status,
        "error": order.error,
        "created_by": order.created_by,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }
