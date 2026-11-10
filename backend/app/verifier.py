# The verify loop. Fixed code, no AI in the checks themselves.
#
# For each available item, one at a time (so the UI fills row by row):
#   1. page check:   the source_quote really is on the page, and the price in it is unit_price
#   2. PayPal check: create a real sandbox order for 1 unit, read it back, compare what PayPal
#                    holds (amount, currency, item name) against the spec. never captured
#   pass -> item.verified with the PayPal order id
#   fail -> item.failed with the exact reason, Claude repairs the item, try again.
#           at most MAX_REPAIRS repairs, then the item stays failed. no fake success.

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from backend.app.paypal_client import (
    PAYPAL_FAILURES,
    PayPalError,
    build_order_body,
    describe_failure,
    first_purchase_unit,
)
from backend.app.spec import SpecError

MAX_REPAIRS = 3

# how far apart the pieces of a quote written with "..." may sit on the page
MAX_QUOTE_GAP_CHARS = 200

# a price as it shows up in page text: $9, $9.50, $1,200.00, 9.00 USD
PRICE_REGEX = re.compile(
    r"[$€£]\s?(\d[\d,]*(?:\.\d{1,2})?)"
    r"|(\d[\d,]*(?:\.\d{1,2})?)\s?(?:USD|EUR|GBP|dollars)\b",
    re.IGNORECASE,
)
# crossed-out text, the fetcher wraps it in ~~ ~~
STRUCK_REGEX = re.compile(r"~~[^~]*~~")


@dataclass
class CheckResult:
    ok: bool
    page_check_ok: bool
    paypal_check_ok: bool | None = None
    paypal_order_id: str | None = None
    reason: str | None = None
    # false when asking Claude to fix the item can't help (PayPal is down, bad credentials)
    repairable: bool = True


# ---- page check ----


def normalize(text):
    # the same squashing on both sides, so line breaks and curly quotes don't cause a miss
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("\xa0", " ")
    return " ".join(text.split()).casefold()


def quote_on_page(quote, page_text):
    # exact match after normalizing. a quote may skip a stretch with "..." like
    # "Sourdough Loaf ... $9", then each piece has to appear in order and close together
    page = normalize(page_text)
    pieces = []
    for piece in re.split(r"\.\.\.|…", quote):
        piece = normalize(piece)
        if piece:
            pieces.append(piece)
    if not pieces:
        return False

    position = 0
    for index, piece in enumerate(pieces):
        found = page.find(piece, position)
        if found == -1:
            return False
        if index > 0 and found - position > MAX_QUOTE_GAP_CHARS:
            return False
        position = found + len(piece)
    return True


def prices_in(text):
    # every price in the text as a Decimal, ignoring anything crossed out
    text = STRUCK_REGEX.sub(" ", text)
    prices = []
    for match in PRICE_REGEX.finditer(text):
        digits = (match.group(1) or match.group(2)).replace(",", "")
        try:
            prices.append(Decimal(digits))
        except InvalidOperation:
            continue
    return prices


def show_price(price):
    return str(Decimal(price).quantize(Decimal("0.01")))


def page_check(item, page_text):
    # returns (ok, reason). reason is None when ok
    if not quote_on_page(item.source_quote, page_text):
        return False, 'The quote "' + item.source_quote + '" is not on the page'

    quoted = prices_in(item.source_quote)
    if not quoted:
        return False, 'The quote "' + item.source_quote + '" has no price in it'

    wanted = Decimal(item.unit_price)
    distinct = sorted(set(quoted))
    if len(distinct) > 1:
        shown = ", ".join(show_price(price) for price in distinct)
        return False, (
            "The quote has more than one price in it (" + shown
            + "), so it doesn't pin down " + item.unit_price
        )
    if distinct[0] != wanted:
        return False, (
            "The page says " + show_price(distinct[0]) + " but the spec says " + item.unit_price
        )

    # variants and add-ons don't carry their own quote, but their price has to at least be
    # a price that is on the page (and not a crossed-out one)
    page_prices = set(prices_in(page_text))
    for variant in item.variants:
        if Decimal(variant.unit_price) not in page_prices:
            return False, (
                'Variant "' + variant.label + '" is priced ' + variant.unit_price
                + " but that price is not on the page"
            )
    for add_on in item.add_ons:
        if Decimal(add_on.price) not in page_prices:
            return False, (
                'Add-on "' + add_on.label + '" is priced ' + add_on.price
                + " but that price is not on the page"
            )
    return True, None


# ---- PayPal check ----


def paypal_check(item, currency, paypal, custom_id=None):
    # returns (ok, reason, order_id, repairable)
    body = build_order_body(
        currency=currency,
        item_name=item.name,
        unit_amount=item.unit_price,
        quantity=1,
        shipping_amount="0.00",
        custom_id=custom_id,
    )
    try:
        created = paypal.create_order(body)
        order_id = created["id"]
        # read it back so we compare against PayPal's record, not our own request
        order = paypal.get_order(order_id)
    except PAYPAL_FAILURES as error:
        # PayPal rejecting the order body (a 4xx about the order itself) is something a
        # better item could fix. a timeout, bad credentials or a 5xx is not
        repairable = (
            isinstance(error, PayPalError) and error.status_code in (400, 422)
        )
        return False, describe_failure(error), None, repairable

    problem = compare_order(order, item, currency)
    if problem:
        return False, problem, order_id, True
    return True, None, order_id, True


def compare_order(order, item, currency):
    # None when PayPal's order matches the spec, else what differs
    purchase_unit = first_purchase_unit(order)
    amount = purchase_unit.get("amount") or {}

    if amount.get("currency_code") != currency:
        return (
            "PayPal has the currency as " + str(amount.get("currency_code"))
            + ", the spec says " + currency
        )
    try:
        paypal_value = Decimal(str(amount.get("value")))
    except InvalidOperation:
        return "PayPal's order has no readable amount"
    if paypal_value != Decimal(item.unit_price):
        return (
            "PayPal has the amount as " + str(amount.get("value"))
            + ", the spec says " + item.unit_price
        )

    items = purchase_unit.get("items") or []
    if not items:
        return "PayPal's order came back with no line items"
    if items[0].get("name") != item.name:
        return (
            'PayPal has the item name as "' + str(items[0].get("name"))
            + '", the spec says "' + item.name + '"'
        )
    return None


def check_item(item, currency, page_text, paypal, custom_id=None):
    page_ok, page_reason = page_check(item, page_text)
    if not page_ok:
        # no point creating a PayPal order for a price the page doesn't back up
        return CheckResult(ok=False, page_check_ok=False, reason=page_reason)

    paypal_ok, paypal_reason, order_id, repairable = paypal_check(
        item, currency, paypal, custom_id
    )
    return CheckResult(
        ok=paypal_ok,
        page_check_ok=True,
        paypal_check_ok=paypal_ok,
        paypal_order_id=order_id,
        reason=paypal_reason,
        repairable=repairable,
    )


# ---- the loop ----


def verify_store(store_id, spec, version, page_text, ai, paypal, emit, recorder):
    # walks every item, repairing as it goes. returns (final spec, counts).
    #   emit(event_type, message, item_id=None, data=None)
    #   recorder.save_run(item_id, attempt, version, result)
    #   recorder.save_spec(spec, note) -> the new version number
    #   ai.repair_item(item, reason, page_text) -> (repaired Item, note)
    counts = {"verified": 0, "failed": 0, "unavailable": 0}
    currency = spec.merchant.currency

    # explicit loop over positions, a repair swaps the item at that position
    for position in range(len(spec.items)):
        item = spec.items[position]
        if not item.available:
            counts["unavailable"] += 1
            continue

        attempt = 0
        while True:
            emit(
                "item.checking",
                "Checking " + item.name + " against the page and PayPal.",
                item.id,
                {"attempt": attempt, "item": item.model_dump()},
            )
            custom_id = "verify-" + str(store_id) + "-" + item.id
            result = check_item(item, currency, page_text, paypal, custom_id)
            recorder.save_run(item.id, attempt, version, result)

            if result.ok:
                counts["verified"] += 1
                emit(
                    "item.verified",
                    item.name + " verified at " + item.unit_price + " " + currency
                    + ", PayPal order " + result.paypal_order_id + ".",
                    item.id,
                    {
                        "attempt": attempt,
                        "paypal_order_id": result.paypal_order_id,
                        "item": item.model_dump(),
                    },
                )
                break

            out_of_repairs = attempt >= MAX_REPAIRS
            final = out_of_repairs or not result.repairable
            emit(
                "item.failed",
                item.name + " failed: " + result.reason + ".",
                item.id,
                {
                    "attempt": attempt,
                    "reason": result.reason,
                    "page_check_ok": result.page_check_ok,
                    "paypal_check_ok": result.paypal_check_ok,
                    "paypal_order_id": result.paypal_order_id,
                    "final": final,
                },
            )
            if final:
                counts["failed"] += 1
                break

            attempt += 1
            emit(
                "item.repairing",
                "Asking Claude to repair " + item.name + " (repair " + str(attempt)
                + " of " + str(MAX_REPAIRS) + ").",
                item.id,
                {"attempt": attempt, "reason": result.reason},
            )
            try:
                repaired, note = ai.repair_item(item, result.reason, page_text)
            except SpecError as error:
                # Claude answered with something that isn't a valid item. that used up a repair
                emit(
                    "item.failed",
                    "The repair for " + item.name + " wasn't a valid item: " + str(error) + ".",
                    item.id,
                    {"attempt": attempt, "reason": str(error), "final": attempt >= MAX_REPAIRS},
                )
                if attempt >= MAX_REPAIRS:
                    counts["failed"] += 1
                    break
                continue
            except Exception as error:  # noqa: BLE001
                # the Claude call itself failed. say so and leave the item failed
                counts["failed"] += 1
                emit(
                    "item.failed",
                    "Couldn't get a repair for " + item.name + ": " + describe_ai_error(error)
                    + ".",
                    item.id,
                    {"attempt": attempt, "reason": describe_ai_error(error), "final": True},
                )
                break

            # the id is ours, a repair doesn't get to rename the row
            repaired = repaired.model_copy(update={"id": item.id})
            items = list(spec.items)
            items[position] = repaired
            notes = list(spec.extraction_notes)
            if note and len(notes) < 40:
                notes.append(("Repair " + str(attempt) + " of " + item.name + ": " + note)[:400])
            spec = spec.model_copy(update={"items": items, "extraction_notes": notes})
            version = recorder.save_spec(spec, "Repair " + str(attempt) + " of " + item.name)
            item = repaired

            if not item.available:
                counts["unavailable"] += 1
                emit(
                    "item.failed",
                    "The repair marked " + item.name + " as not available, so it won't be sold.",
                    item.id,
                    {"attempt": attempt, "reason": "Marked not available", "final": True,
                     "unavailable": True, "item": item.model_dump()},
                )
                break

    return spec, counts


def describe_ai_error(error):
    text = str(error).strip()
    if not text:
        return type(error).__name__
    return (type(error).__name__ + ": " + text)[:300]
