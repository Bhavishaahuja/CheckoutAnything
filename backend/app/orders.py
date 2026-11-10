# Buying. The price is always worked out here from the verified spec, a price sent by the
# client is never read. Then: create the PayPal order paid with the saved sandbox buyer wallet
# (vault id), which captures in the same call, and record it.
#
# With CHECK_URL set, an agent's order takes the other road (place_order_through_check): the
# same priced order goes to the Check service, which places a hold at PayPal, checks the order
# against what the human asked for, and captures it or holds it for the human.
#
# Price math, all in Decimal:
#   unit  = (variant price if a variant was picked, else the item price) + every add-on price
#   total = unit * quantity + flat shipping (once per order)

import uuid
from dataclasses import dataclass
from decimal import Decimal

from backend.app.check_client import CheckError
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
    # the same line in two parts, for Check: the item with its add-ons, and the variant
    item_name: str
    variant_label: str | None
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
    item_name = item.name
    variant_label = None

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
        variant_label = chosen.label

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
        item_name += " + " + chosen.label

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
        item_name=item_name,
        variant_label=variant_label,
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


# Check's limits on an order item (check/docs/api.md, OrderItemIn)
CHECK_NAME_LENGTH = 200
CHECK_SIZE_LENGTH = 100
# Check only takes US dollars
CHECK_CURRENCY = "USD"
# an order in one of these is finished, Check won't change it again
CHECK_FINAL_STATUSES = ("captured", "voided", "failed")
# the confirm page's third button, as Check records it on the approval
ACCEPT_FIX = "accept_fix"


def check_items(quote):
    # one line, the way Check wants it: the variant goes in "size", which is the field its
    # check compares with the size or portion the human named
    item = {
        "name": quote.item_name[:CHECK_NAME_LENGTH],
        "quantity": quote.quantity,
        "unit_price": str(quote.unit_amount),
    }
    if quote.variant_label:
        item["size"] = quote.variant_label[:CHECK_SIZE_LENGTH]
    return [item]


def apply_check_order(order, check_order):
    # copy what Check says about an order onto our row. takes the agent's four fields
    # ({id, status, review_state, total}) or the merchant's full order object
    order.status = str(check_order.get("status") or order.status)
    order.review_state = check_order.get("review_state")
    if check_order.get("paypal_order_id"):
        order.paypal_order_id = check_order["paypal_order_id"]
    if check_order.get("capture_id"):
        order.capture_id = check_order["capture_id"]
    intent_check = check_order.get("intent_check")
    if isinstance(intent_check, dict):
        order.check_verdict = intent_check.get("verdict")
        order.check_reason = intent_check.get("reason")
    approval = check_order.get("approval")
    if isinstance(approval, dict):
        if approval.get("decision_ms") is not None:
            order.decision_ms = approval["decision_ms"]
        if approval.get("action"):
            order.review_action = approval["action"]
    if check_order.get("replaced_by_order_id") is not None:
        order.check_replaced_by_id = check_order["replaced_by_order_id"]
    if check_order.get("replaces_order_id") is not None:
        order.check_replaces_id = check_order["replaces_order_id"]


def waiting_for_replacement(order):
    # the human accepted the fix and Check voided this order, but we haven't seen which order
    # replaced it yet. Check writes that link last, after the new order's own hold and check,
    # so a read can land in between
    return order.review_action == ACCEPT_FIX and order.check_replaced_by_id is None


def replacement_description(check_order, fallback):
    # the line for the grid, in the same shape as ours: "Trail runner (Size 8)"
    items = check_order.get("items")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return fallback
    first = items[0]
    description = str(first.get("name") or fallback)
    if first.get("size"):
        description += " (" + str(first["size"]) + ")"
    return description[:MAX_NAME_LENGTH]


def adopt_replacement(session, original, check_order):
    # the order Check placed when the human accepted the fix. it never came through our buy
    # endpoint, so there is no row for it yet: make one, at the same store and for the same
    # mandate as the order it replaces. the item and price are the Check catalog's, not ours
    items = check_order.get("items")
    quantity = original.quantity
    if isinstance(items, list) and items and isinstance(items[0], dict):
        if isinstance(items[0].get("quantity"), int):
            quantity = items[0]["quantity"]
    replacement = Order(
        store_id=original.store_id,
        # the nearest thing we have: the fix is another version of the item that was asked for
        item_id=original.item_id,
        variant_id=None,
        add_on_ids="",
        description=replacement_description(check_order, original.description),
        quantity=quantity,
        total=str(check_order.get("total") or original.total),
        currency=str(check_order.get("currency") or original.currency),
        status="failed",
        created_by=original.created_by,
        check_mandate_id=original.check_mandate_id,
        check_order_id=check_order.get("id"),
        check_replaces_id=original.check_order_id,
    )
    apply_check_order(replacement, check_order)
    session.add(replacement)
    return replacement


def place_order_through_check(session, check, mandate_for, vault_id, store, quote,
                              created_by="agent"):
    # sends a priced order to Check instead of paying for it here, and saves the Order row
    # either way. Check places the hold with the same saved wallet, runs its check and
    # captures or holds. nothing is captured in this function.
    # mandate_for(store) sends the human's request to Check and returns the mandate id. it's
    # called here, after everything that can be refused up front, so those leave no mandate
    if not vault_id:
        raise OrderError(
            "BUYER_VAULT_ID isn't set on the API, so there's no saved wallet to pay with", 503
        )
    if quote.currency != CHECK_CURRENCY:
        raise OrderError("Check only takes " + CHECK_CURRENCY + " orders, this store sells in "
                         + quote.currency)

    try:
        mandate_id = mandate_for(store)
    except CheckError as error:
        raise OrderError("Check couldn't take the request: " + str(error), 502) from error

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
        check_mandate_id=mandate_id,
    )

    try:
        placed = check.create_order(
            mandate_id=mandate_id,
            items=check_items(quote),
            shipping=str(quote.shipping),
            vault_id=vault_id,
            merchant=store.merchant_name,
        )
    except CheckError as error:
        order.error = "Check: " + str(error)
        session.add(order)
        session.commit()
        return order

    order.check_order_id = placed.get("id")
    apply_check_order(order, placed)
    held_total = placed.get("total")
    if order.status == "failed":
        order.error = "PayPal wouldn't place the hold"
    elif held_total is None or Decimal(str(held_total)) != quote.total:
        # the same guard as the capture check above: what Check holds has to be our total
        order.error = "Check holds " + str(held_total) + " but the order total is " + \
            str(quote.total)

    # the agent's answer has no reason and no PayPal ids. the merchant's view has both
    if check.can_read and order.check_order_id is not None:
        try:
            apply_check_order(order, check.get_order(order.check_order_id))
        except CheckError:
            # the order is placed either way. the grid picks the details up on its next read
            pass

    session.add(order)
    session.commit()
    return order


def refresh_check_orders(session, check, orders):
    # an order on hold changes when a human decides, so re-read the ones that aren't finished
    # (or that we never got the check result for). one call to Check, however many there are
    if check is None or not check.can_read:
        return
    stale = []
    for order in orders:
        if order.check_order_id is None:
            continue
        if order.status not in CHECK_FINAL_STATUSES or order.check_verdict is None:
            stale.append(order)
        elif waiting_for_replacement(order):
            stale.append(order)
    if not stale:
        return
    try:
        listed = check.list_orders()
    except CheckError:
        # show what we have, the next read tries again
        return
    by_id = {}
    for check_order in listed:
        by_id[check_order.get("id")] = check_order
    for order in stale:
        check_order = by_id.get(order.check_order_id)
        if check_order is None:
            # older than the newest 200 at Check, ask for it by id
            try:
                check_order = check.get_order(order.check_order_id)
            except CheckError:
                continue
        apply_check_order(order, check_order)

    # an accepted fix leaves a new order at Check that we have no row for. give it one, so the
    # grid can show the old row as fixed and point at the new one
    known = set()
    for order in orders:
        if order.check_order_id is not None:
            known.add(order.check_order_id)
    for order in stale:
        replacement_id = order.check_replaced_by_id
        if replacement_id is None or replacement_id in known:
            continue
        check_order = by_id.get(replacement_id)
        if check_order is None:
            try:
                check_order = check.get_order(replacement_id)
            except CheckError:
                # the link is saved, so this is tried again on the next read
                order.check_replaced_by_id = None
                continue
        orders.append(adopt_replacement(session, order, check_order))
        known.add(replacement_id)
    session.commit()


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
        # all None on an order that was paid here and not sent through Check
        "check_order_id": order.check_order_id,
        "check_mandate_id": order.check_mandate_id,
        "review_state": order.review_state,
        "check_verdict": order.check_verdict,
        "check_reason": order.check_reason,
        "decision_ms": order.decision_ms,
        "review_action": order.review_action,
        # our own order ids for the two ends of an accepted fix. list_orders fills them in,
        # since it takes the whole list to turn Check's ids into ours
        "replaced_by_order_id": None,
        "replaces_order_id": None,
    }
