from decimal import Decimal

import pytest

from backend.app.orders import OrderError, price_order
from backend.tests.fakes import FERNWOOD_SPEC, HOLLOWBROOK_SPEC, QUILL_SPEC, spec_copy

BAKERY = spec_copy(HOLLOWBROOK_SPEC)
BAKERY_VERIFIED = {"sourdough-loaf", "seeded-rye", "cinnamon-morning-bun", "olive-focaccia"}


def quote(spec, verified, *args, **kwargs):
    return price_order(spec, verified, *args, **kwargs)


def test_plain_item_plus_flat_shipping():
    priced = quote(BAKERY, BAKERY_VERIFIED, "seeded-rye")
    assert priced.unit_amount == Decimal("7.00")
    assert priced.item_total == Decimal("7.00")
    assert priced.shipping == Decimal("6.00")
    assert priced.total == Decimal("13.00")
    assert priced.currency == "USD"


def test_the_demo_order_half_sourdough_sliced():
    priced = quote(BAKERY, BAKERY_VERIFIED, "sourdough-loaf", "half", ["sliced"], 1)
    # the half loaf price replaces the loaf price, sliced is added on top
    assert priced.unit_amount == Decimal("6.00")
    assert priced.total == Decimal("12.00")
    assert priced.line_name == "Sourdough Loaf (Half loaf) + Sliced"


def test_quantity_multiplies_the_unit_and_shipping_is_charged_once():
    priced = quote(BAKERY, BAKERY_VERIFIED, "sourdough-loaf", "half", ["sliced"], 3)
    assert priced.item_total == Decimal("18.00")
    assert priced.total == Decimal("24.00")


def test_cents_stay_exact():
    priced = quote(BAKERY, BAKERY_VERIFIED, "cinnamon-morning-bun", quantity=3)
    assert priced.item_total == Decimal("13.50")
    assert priced.total == Decimal("19.50")
    assert str(priced.total) == "19.50"


def test_variant_replaces_the_base_price():
    spec = spec_copy(FERNWOOD_SPEC)
    priced = quote(spec, {"wool-camp-blanket"}, "wool-camp-blanket", "large", [], 2)
    assert priced.unit_amount == Decimal("160.00")
    assert priced.total == Decimal("326.00")


def test_add_on_with_no_shipping():
    spec = spec_copy(QUILL_SPEC)
    priced = quote(spec, {"full-body"}, "full-body", None, ["background"], 1)
    assert priced.shipping == Decimal("0.00")
    assert priced.total == Decimal("105.00")


def test_unverified_item_cant_be_bought():
    with pytest.raises(OrderError) as error:
        quote(BAKERY, {"seeded-rye"}, "olive-focaccia")
    assert "verification" in str(error.value)


def test_unavailable_item_cant_be_bought_even_if_someone_says_it_is_verified():
    with pytest.raises(OrderError):
        quote(BAKERY, {"butter-croissant"}, "butter-croissant")


def test_unknown_item_variant_and_add_on():
    with pytest.raises(OrderError) as error:
        quote(BAKERY, BAKERY_VERIFIED, "bagel")
    assert error.value.status_code == 404
    with pytest.raises(OrderError):
        quote(BAKERY, BAKERY_VERIFIED, "sourdough-loaf", "quarter")
    with pytest.raises(OrderError):
        quote(BAKERY, BAKERY_VERIFIED, "sourdough-loaf", None, ["toasted"])


def test_the_same_add_on_twice_is_rejected():
    with pytest.raises(OrderError):
        quote(BAKERY, BAKERY_VERIFIED, "sourdough-loaf", None, ["sliced", "sliced"])


@pytest.mark.parametrize("quantity", [0, -1, 101, 1.5, "2", True, None])
def test_bad_quantities(quantity):
    with pytest.raises(OrderError):
        quote(BAKERY, BAKERY_VERIFIED, "seeded-rye", quantity=quantity)
