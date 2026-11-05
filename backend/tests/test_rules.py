# The hard rules, on real model objects with nothing saved. No database, no Claude, no PayPal

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.app.intent.rules import (
    RuleResult,
    check_currency,
    check_expiry,
    check_hard_rules,
    check_merchant,
    check_price,
    hard_rules_verdict,
)
from backend.app.models import Mandate, Order, Verdict

NOW = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
ONE_ITEM = [{"name": "Trail runner", "quantity": 1, "unit_price": "115.00"}]


def make_mandate(max_price="120.00", inclusive=True, merchant="Fernwood Supply Co",
                 expires_at=None, currency=None):
    rules = {"currency": currency}
    if max_price is None:
        cap = None
    else:
        cap = Decimal(max_price)
    return Mandate(
        buyer_label="Sam",
        raw_request="trail runners",
        rules=rules,
        max_price=cap,
        max_price_inclusive=inclusive,
        merchant=merchant,
        expires_at=expires_at,
    )


def make_order(total="100.00", shipping="0.00", currency="USD", items=None):
    if items is None:
        items = ONE_ITEM
    if shipping is None:
        shipping_amount = None
    else:
        shipping_amount = Decimal(shipping)
    return Order(
        mandate_id=1,
        items=items,
        total=Decimal(total),
        shipping_amount=shipping_amount,
        currency=currency,
    )


# ---- price ----


def test_price_under_cap_passes():
    result = check_price(make_mandate(), make_order(total="100.00"))

    assert result.passed is True
    assert result.reason == "Order is $100.00, within the $120.00 cap"


def test_price_over_cap_fails_with_exact_reason():
    result = check_price(make_mandate(), make_order(total="142.00"))

    assert result.passed is False
    assert result.reason == "Order is $142.00, mandate cap is $120.00"


def test_one_cent_over_cap_fails():
    assert check_price(make_mandate(), make_order(total="120.01")).passed is False


def test_exactly_at_cap_passes_for_up_to():
    result = check_price(make_mandate(inclusive=True), make_order(total="120.00"))

    assert result.passed is True
    assert result.reason == "Order is $120.00, within the $120.00 cap"


def test_exactly_at_cap_fails_for_under():
    result = check_price(make_mandate(inclusive=False), make_order(total="120.00"))

    assert result.passed is False
    assert result.reason == "Order is $120.00, mandate requires under $120.00"


def test_one_cent_below_cap_passes_for_under():
    result = check_price(make_mandate(inclusive=False), make_order(total="119.99"))

    assert result.passed is True
    assert result.reason == "Order is $119.99, under the $120.00 cap"


def test_no_cap_passes():
    result = check_price(make_mandate(max_price=None), make_order(total="9999.00"))

    assert result.passed is True
    assert result.reason == "Mandate sets no price cap"


def test_price_compares_as_decimal_not_float():
    # as floats, 0.1 + 0.2 is 0.30000000000000004, which would land just over a 0.30 cap
    total = Decimal("0.10") + Decimal("0.20")

    assert check_price(make_mandate(max_price="0.30"), make_order(total=str(total))).passed is True


def test_same_amount_with_different_scale_is_at_the_cap():
    # 120.0 and 120.00 are equal as Decimals, this shouldn't count as over
    assert check_price(make_mandate(max_price="120.0"), make_order(total="120.00")).passed is True


def test_reason_breaks_out_shipping():
    result = check_price(make_mandate(), make_order(total="125.00", shipping="10.00"))

    assert result.passed is False
    assert result.reason == (
        "Order is $125.00 ($115.00 item + $10.00 shipping), mandate cap is $120.00"
    )


def test_shipping_counts_toward_the_cap():
    # the item alone is under the cap, but the total is what gets charged and disputed
    assert check_price(make_mandate(), make_order(total="125.00", shipping="10.00")).passed is False


def test_reason_says_items_for_more_than_one_unit():
    items = [{"name": "Wool hiking socks", "quantity": 2, "unit_price": "60.00"}]

    result = check_price(make_mandate(), make_order(total="130.00", shipping="10.00", items=items))

    assert result.reason == (
        "Order is $130.00 ($120.00 items + $10.00 shipping), mandate cap is $120.00"
    )


def test_older_order_without_saved_shipping_has_no_breakdown():
    result = check_price(make_mandate(), make_order(total="142.00", shipping=None))

    assert result.reason == "Order is $142.00, mandate cap is $120.00"


def test_price_skipped_when_cap_is_in_another_currency():
    # 100 euros isn't comparable to a dollar total, even though 150 is "over" 100
    mandate = make_mandate(max_price="100.00", currency="EUR")

    result = check_price(mandate, make_order(total="150.00"))

    assert result.passed is True
    assert result.reason == "Skipped, cap is in EUR"


def test_price_compared_when_mandate_currency_matches():
    mandate = make_mandate(currency="USD")

    assert check_price(mandate, make_order(total="142.00")).passed is False


def test_price_treats_null_mandate_currency_as_usd():
    mandate = make_mandate(currency=None)

    assert check_price(mandate, make_order(total="142.00")).passed is False


def test_price_reason_uses_the_code_for_other_currencies():
    mandate = make_mandate(max_price="100.00", currency="EUR")

    result = check_price(mandate, make_order(total="142.00", currency="EUR"))

    assert result.passed is False
    assert result.reason == "Order is 142.00 EUR, mandate cap is 100.00 EUR"


# ---- merchant ----


@pytest.mark.parametrize("merchant", [
    "Fernwood Supply Co",
    "Fernwood",
    "fernwood",
    "Fernwood Supply",
    "fernwood supply co",
    "FERNWOOD SUPPLY CO",
    "Fernwood Supply Co.",
    "  Fernwood   Supply  Co  ",
])
def test_store_name_and_aliases_pass(merchant):
    result = check_merchant(make_mandate(merchant=merchant))

    assert result.passed is True
    assert result.reason == "Mandate store matches Fernwood Supply Co"


def test_wrong_store_fails_with_exact_reason():
    # the wrong-store demo scenario
    result = check_merchant(make_mandate(merchant="Ridgeline Outdoors"))

    assert result.passed is False
    assert result.reason == "Mandate says Ridgeline Outdoors, order is at Fernwood Supply Co"


def test_name_that_only_contains_an_alias_fails():
    # matching is on the whole name, a different business doesn't pass by sharing a word
    assert check_merchant(make_mandate(merchant="Fernwood Outlet")).passed is False


@pytest.mark.parametrize("merchant", [None, "", "   "])
def test_no_store_named_passes(merchant):
    result = check_merchant(make_mandate(merchant=merchant))

    assert result.passed is True
    assert result.reason == "Mandate names no store"


# ---- expiry ----


def test_mandate_not_expired_passes():
    mandate = make_mandate(expires_at=NOW + timedelta(days=1))

    result = check_expiry(mandate, NOW)

    assert result.passed is True
    assert result.reason == "Mandate is valid until 2026-11-05 12:00 UTC"


def test_expired_mandate_fails():
    mandate = make_mandate(expires_at=NOW - timedelta(days=1))

    result = check_expiry(mandate, NOW)

    assert result.passed is False
    assert result.reason == "Mandate expired 2026-11-03 12:00 UTC"


def test_exactly_at_expiry_is_still_valid():
    assert check_expiry(make_mandate(expires_at=NOW), NOW).passed is True


def test_one_second_after_expiry_fails():
    assert check_expiry(make_mandate(expires_at=NOW), NOW + timedelta(seconds=1)).passed is False


def test_no_expiry_passes():
    result = check_expiry(make_mandate(expires_at=None), NOW)

    assert result.passed is True
    assert result.reason == "Mandate has no expiry"


def test_expiry_compares_real_moments_across_time_zones():
    # 23:00 in UTC-5 is 04:00 the next day in UTC, so this is still 4 hours away
    chicago_ish = timezone(timedelta(hours=-5))
    expires_at = datetime(2026, 11, 4, 23, 0, 0, tzinfo=chicago_ish)
    now = datetime(2026, 11, 5, 0, 0, 0, tzinfo=timezone.utc)

    result = check_expiry(make_mandate(expires_at=expires_at), now)

    assert result.passed is True
    assert result.reason == "Mandate is valid until 2026-11-05 04:00 UTC"


def test_naive_expiry_from_sqlite_is_read_as_utc():
    expires_at = datetime(2026, 11, 4, 12, 0, 0)

    assert check_expiry(make_mandate(expires_at=expires_at), NOW).passed is True
    later = NOW + timedelta(seconds=1)
    assert check_expiry(make_mandate(expires_at=expires_at), later).passed is False


# ---- currency ----


def test_matching_currency_passes():
    result = check_currency(make_mandate(currency="USD"), make_order())

    assert result.passed is True
    assert result.reason == "Both are in USD"


def test_different_currency_fails():
    result = check_currency(make_mandate(currency="EUR"), make_order())

    assert result.passed is False
    assert result.reason == "Mandate is in EUR, order is in USD"


def test_no_mandate_currency_passes():
    result = check_currency(make_mandate(currency=None), make_order())

    assert result.passed is True
    assert result.reason == "Mandate names no currency"


def test_mandate_parsed_before_currency_existed_passes():
    # older rows have no "currency" key in rules at all
    mandate = make_mandate()
    mandate.rules = {"item": "trail runners"}

    assert check_currency(mandate, make_order()).passed is True


# ---- all together ----


def results_by_rule(results):
    by_rule = {}
    for result in results:
        by_rule[result.rule] = result
    return by_rule


def test_returns_one_result_per_rule():
    results = check_hard_rules(make_mandate(), make_order(), now=NOW)

    names = []
    for result in results:
        assert isinstance(result, RuleResult)
        names.append(result.rule)
    assert names == ["price", "merchant", "expiry", "currency"]


def test_clean_order_has_no_hard_verdict():
    # passing the hard rules doesn't make it a match, Claude still has to look at it
    results = check_hard_rules(make_mandate(), make_order(), now=NOW)

    for result in results:
        assert result.passed is True
    assert hard_rules_verdict(results) is None


@pytest.mark.parametrize(("mandate_args", "order_args", "failed_rule"), [
    ({}, {"total": "142.00"}, "price"),
    ({"merchant": "Ridgeline Outdoors"}, {}, "merchant"),
    ({"expires_at": NOW - timedelta(days=1)}, {}, "expiry"),
    ({"currency": "EUR"}, {}, "currency"),
])
def test_any_single_failure_is_a_mismatch(mandate_args, order_args, failed_rule):
    results = check_hard_rules(make_mandate(**mandate_args), make_order(**order_args), now=NOW)

    failed = []
    for result in results:
        if not result.passed:
            failed.append(result.rule)
    assert failed == [failed_rule]
    assert hard_rules_verdict(results) == Verdict.mismatch
    # same string the decisions table stores
    assert hard_rules_verdict(results) == "mismatch"


def test_every_failure_gets_reported():
    mandate = make_mandate(merchant="Ridgeline Outdoors", expires_at=NOW - timedelta(days=1))

    results = check_hard_rules(mandate, make_order(total="142.00"), now=NOW)

    by_rule = results_by_rule(results)
    assert by_rule["price"].passed is False
    assert by_rule["merchant"].passed is False
    assert by_rule["expiry"].passed is False
    assert by_rule["currency"].passed is True


def test_euro_cap_only_fails_on_currency():
    # "under 100 euros" on a $50 dollar order: the currency rule carries the fail
    mandate = make_mandate(max_price="100.00", inclusive=False, currency="EUR")

    results = check_hard_rules(mandate, make_order(total="50.00"), now=NOW)

    by_rule = results_by_rule(results)
    assert by_rule["price"].passed is True
    assert by_rule["price"].reason == "Skipped, cap is in EUR"
    assert by_rule["currency"].passed is False
    assert by_rule["currency"].reason == "Mandate is in EUR, order is in USD"
    assert hard_rules_verdict(results) == Verdict.mismatch


def test_now_defaults_to_the_real_clock():
    # expired years ago, so this fails whenever the suite runs
    long_gone = datetime(2020, 1, 1, tzinfo=timezone.utc)

    results = check_hard_rules(make_mandate(expires_at=long_gone), make_order())

    assert results_by_rule(results)["expiry"].passed is False
