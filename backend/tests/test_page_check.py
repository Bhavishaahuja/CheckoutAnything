from decimal import Decimal

from backend.app.fetcher import html_to_text
from backend.app.spec import parse_item
from backend.app.verifier import page_check, prices_in, quote_on_page
from backend.tests.fakes import (
    FERNWOOD_SPEC,
    HOLLOWBROOK_SPEC,
    QUILL_SPEC,
    demo_page,
    simple_item,
    spec_copy,
)

BAKERY = demo_page("hollowbrook-bakery").text


def item(**fields):
    return parse_item(simple_item(**fields))


def test_every_demo_item_passes_against_its_own_page():
    stores = [
        ("fernwood-thistle-goods", FERNWOOD_SPEC),
        ("quill-pipkin-studio", QUILL_SPEC),
        ("hollowbrook-bakery", HOLLOWBROOK_SPEC),
    ]
    for slug, data in stores:
        page_text = demo_page(slug).text
        for one in spec_copy(data).items:
            ok, reason = page_check(one, page_text)
            assert ok, slug + " " + one.id + ": " + str(reason)


def test_quote_that_isnt_on_the_page_fails():
    ok, reason = page_check(
        item(item_id="bagel", name="Bagel", price="3.00", quote="Bagel $3"), BAKERY
    )
    assert not ok
    assert "not on the page" in reason


def test_price_that_differs_from_the_quote_fails():
    ok, reason = page_check(
        item(item_id="bun", name="Cinnamon Morning Bun", price="4.00",
             quote="Cinnamon Morning Bun orange zest, lots of sugar | $4.50"),
        BAKERY,
    )
    assert not ok
    assert "4.50" in reason and "4.00" in reason


def test_crossed_out_price_is_not_the_price():
    # the old $8 is on the page, but only struck through
    ok, reason = page_check(
        item(item_id="rye", name="Seeded Rye", price="8.00",
             quote="Seeded Rye caraway, sunflower, a little honey | ~~$8~~ $7"),
        BAKERY,
    )
    assert not ok
    assert "7.00" in reason


def test_quote_with_two_live_prices_fails():
    page_text = demo_page("quill-pipkin-studio").text
    ok, reason = page_check(
        item(item_id="headshot", name="Headshot", price="40.00",
             quote="Headshots are $40, half body $65"),
        page_text,
    )
    assert not ok
    assert "more than one price" in reason


def test_quote_without_a_price_fails():
    ok, reason = page_check(
        item(item_id="focaccia", name="Olive Focaccia", price="11.00",
             quote="Olive Focaccia* by the slab, serves four"),
        BAKERY,
    )
    assert not ok
    assert "no price" in reason


def test_footnote_price_passes():
    ok, _reason = page_check(
        item(item_id="focaccia", name="Olive Focaccia", price="11.00",
             quote="Olive Focaccia is $11 a slab this season"),
        BAKERY,
    )
    assert ok


def test_variant_price_has_to_be_on_the_page():
    ok, reason = page_check(
        item(item_id="sourdough", name="Sourdough Loaf", price="9.00",
             quote="Sourdough Loaf 48 hour ferment, crackly crust | $9",
             variants=[{"id": "half", "label": "Half loaf", "unit_price": "4.00"}]),
        "| Sourdough Loaf 48 hour ferment, crackly crust | $9\n| Half loaf $5 |",
    )
    assert not ok
    assert "Half loaf" in reason


def test_add_on_price_has_to_be_on_the_page():
    ok, reason = page_check(
        item(item_id="sourdough", name="Sourdough Loaf", price="9.00",
             quote="Sourdough Loaf 48 hour ferment, crackly crust | $9",
             add_ons=[{"id": "sliced", "label": "Sliced", "price": "2.00"}]),
        BAKERY,
    )
    assert not ok
    assert "Sliced" in reason


def test_quote_matching_ignores_case_spacing_and_curly_quotes():
    assert quote_on_page("sourdough   loaf 48 HOUR ferment", BAKERY)
    assert quote_on_page("you'd like", "email us what you’d like")


def test_quote_with_an_ellipsis_matches_pieces_in_order():
    assert quote_on_page("Sourdough Loaf ... $9", BAKERY)
    # right pieces, wrong order
    assert not quote_on_page("$9 ... Sourdough Loaf 48 hour", BAKERY)
    # pieces that are both on the page but far apart
    assert not quote_on_page("Hollowbrook Bakery ... fictional bakery", BAKERY)


def test_prices_in_reads_the_usual_shapes():
    assert prices_in("$9") == [Decimal("9")]
    assert prices_in("only $4.50 today") == [Decimal("4.50")]
    assert prices_in("$1,200.00") == [Decimal("1200.00")]
    assert prices_in("12.00 USD") == [Decimal("12.00")]
    assert prices_in("~~$8~~ $7") == [Decimal("7")]
    assert prices_in("Extra character +50%") == []
    assert prices_in("serves four, 48 hour ferment") == []


def test_struck_text_is_marked_and_scripts_are_dropped():
    title, text = html_to_text(
        "<html><head><title>Shop</title><style>.a{}</style></head><body>"
        "<script>var price = '$99'</script><p>Rye <s>$8</s> $7</p></body></html>"
    )
    assert title == "Shop"
    assert text == "Rye ~~$8~~ $7"
