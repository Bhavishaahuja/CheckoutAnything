# What Reset demo leaves on the Checkout Anything side, from the real recorded fixtures (replay
# mode): Fernwood all live except the Wool Camp Blanket, whose $85 price waits for the merchant to
# confirm on camera, Hollowbrook all live, Quill & Pipkin not connected at all. Plus: the reset asks
# Check to reset first and stops if Check says no, and the seed orders Check places use the
# stores' real prices and variants.

import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app import review, shop
from backend.app.check_client import CheckError
from backend.app.db import create_tables, new_session
from backend.app.demo import load_fixture
from backend.app.events import bus
from backend.app.models import Order, Store
from backend.app.orders import check_items, price_order
from backend.app.spec import parse_spec
from backend.tests.fakes import FakeCheck
from backend.tests.test_api import World, connect_store, wait_for_runs, wait_until_done

SEED_ORDERS_FILE = (
    Path(__file__).resolve().parents[2] / "check" / "backend" / "app" / "demo_seed_orders.py"
)


@pytest.fixture
def publish_bakery(monkeypatch):
    # the real rule, conftest turns it off for the other tests
    monkeypatch.setattr(review, "PUBLISHED_ON_CONNECT", {"hollowbrook-bakery"})


@pytest.fixture
def check():
    return FakeCheck()


def fresh_database():
    create_tables()
    session = new_session()
    shop.wipe_everything(session)
    session.close()
    bus.clear()


@pytest.fixture
def replay_world(check):
    fresh_database()
    return World(demo_mode="replay", check=check)


def reset_and_wait(client):
    response = client.post("/demo/reset", json={})
    assert response.status_code == 202, response.text
    for one in response.json()["stores"]:
        wait_until_done(client, one["store_id"])
    wait_for_runs()
    return response.json()


def review_by_name(client):
    found = {}
    for store in client.get("/stores").json()["stores"]:
        found[store["merchant_name"]] = (
            store, client.get("/stores/" + str(store["id"]) + "/review").json()
        )
    return found


def test_reset_leaves_the_stores_ready_for_the_video(replay_world, check, publish_bakery):
    with TestClient(replay_world.app) as client:
        # manual testing left Quill & Pipkin connected
        connect_store(client, "https://stores.example/quill-pipkin-studio/")
        wait_for_runs()

        started = reset_and_wait(client)
        assert check.resets == 1
        assert started["check_reset"]["state"] == "running"

        stores = review_by_name(client)
        # no Quill & Pipkin chip and nothing else left over
        assert sorted(stores) == ["Fernwood & Thistle Goods", "Hollowbrook Bakery"]

        fernwood, fernwood_review = stores["Fernwood & Thistle Goods"]
        assert fernwood["status"] == "live"
        assert fernwood["counts"]["verified"] == 6
        assert fernwood["counts"]["live"] == 5
        for item in fernwood_review["items"]:
            if item["item_id"] == "wool-camp-blanket":
                # verified but waiting: the price cell is amber and nobody has confirmed it
                assert item["published"] is False
                price_flags = [flag for flag in item["flags"] if flag["field"] == "unit_price"]
                assert len(price_flags) == 1
                assert price_flags[0]["resolved"] is False
            else:
                assert item["published"] is True, item

        bakery, bakery_review = stores["Hollowbrook Bakery"]
        assert bakery["counts"]["verified"] == bakery["counts"]["live"] == 4
        # the sold out croissant is the "Not for sale on the page" row
        assert bakery["counts"]["unavailable"] == 1
        published = {}
        for item in bakery_review["items"]:
            published[item["item_id"]] = item["published"]
        assert published["sourdough-loaf"] is True
        assert published["butter-croissant"] is False

        # our own orders table starts empty. the orders live at Check
        assert client.get("/orders").json()["orders"] == []


def test_check_saying_no_stops_the_reset_before_anything_is_wiped(replay_world, check):
    with TestClient(replay_world.app) as client:
        store_id, _store = connect_store(client)
        check.fail_reset = CheckError("Someone opened the review for order 42", 409)

        response = client.post("/demo/reset", json={})
        assert response.status_code == 409
        assert "order 42" in response.json()["detail"]
        # the store is still here
        ids = [store["id"] for store in client.get("/stores").json()["stores"]]
        assert ids == [store_id]


def test_the_order_check_protects_keeps_its_row_here(replay_world, check, publish_bakery):
    # the order the sandbox dispute is on came through the agent path, so we have a row for it.
    # Check keeps it (PROTECTED_ORDER_IDS), and the Orders tab has to keep showing it
    with TestClient(replay_world.app) as client:
        old_store_id, _store = connect_store(
            client, "https://stores.example/fernwood-thistle-goods/"
        )
        session = new_session()
        try:
            for check_order_id in (41, 42):
                session.add(Order(
                    store_id=old_store_id, item_id="wool-camp-blanket", variant_id="large",
                    description="Wool Camp Blanket (Large)", quantity=1, total="146.00",
                    status="captured", created_by="agent", check_order_id=check_order_id,
                    review_state="approved", check_verdict="mismatch",
                ))
            session.commit()
        finally:
            session.close()

        def reset_keeping_41():
            check.resets += 1
            return {"state": "running", "protected_order_ids": [41]}

        check.reset_demo = reset_keeping_41
        reset_and_wait(client)

        session = new_session()
        try:
            rows = list(session.execute(select(Order)).scalars())
            assert [row.check_order_id for row in rows] == [41]
            fernwood = session.get(Store, rows[0].store_id)
            # moved to the reconnected Fernwood, the old store row is gone
            assert fernwood.id != old_store_id
            assert fernwood.merchant_name == "Fernwood & Thistle Goods"
            assert session.get(Store, old_store_id) is None
        finally:
            session.close()

        names = []
        for store in client.get("/stores").json()["stores"]:
            names.append(store["merchant_name"])
        assert sorted(names) == ["Fernwood & Thistle Goods", "Hollowbrook Bakery"]
        listed = client.get("/orders").json()["orders"]
        assert len(listed) == 1
        assert listed[0]["store_name"] == "Fernwood & Thistle Goods"


def test_reset_without_check_still_resets_the_stores():
    fresh_database()
    with TestClient(World(demo_mode="replay").app) as client:
        started = reset_and_wait(client)
        assert started["check_reset"] is None
        assert len(started["stores"]) == 2


# ---- Check's seed orders against the real catalogs ----


def load_seed_orders():
    # straight from the file: it has no imports, and the check package can't be imported here
    spec = importlib.util.spec_from_file_location("demo_seed_orders", SEED_ORDERS_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_spec(slug):
    fixture = load_fixture("https://stores.example/" + slug + "/")
    data = dict(fixture["spec"])
    data["source_url"] = "https://stores.example/" + slug + "/"
    return parse_spec(data)


def test_every_seed_order_is_a_real_catalog_line_at_its_real_price():
    seed = load_seed_orders()
    store_names = {
        "fernwood-thistle-goods": seed.FERNWOOD,
        "hollowbrook-bakery": seed.HOLLOWBROOK,
    }
    for order in seed.SEED_ORDERS:
        catalog = order["catalog"]
        spec = fixture_spec(catalog["store"])
        # the mandate names the store the item is really from
        assert spec.merchant.name == store_names[catalog["store"]] == order["store"]

        quantity = order["items"][0]["quantity"]
        every_item = set()
        for item in spec.items:
            every_item.add(item.id)
        quote = price_order(
            spec, every_item, catalog["item_id"], catalog.get("variant_id"),
            catalog.get("add_on_ids"), quantity,
        )
        # exactly what Checkout Anything would send Check for that line
        expected = check_items(quote)
        assert len(order["items"]) == 1
        sent = dict(order["items"][0])
        assert sent == expected[0], order["name"]
        assert seed.SHIPPING == str(quote.shipping)


def test_the_blanket_sizes_are_the_real_ones():
    spec = fixture_spec("fernwood-thistle-goods")
    blanket = spec.find_item("wool-camp-blanket")
    sizes = {"Small": blanket.unit_price}
    for variant in blanket.variants:
        sizes[variant.label] = variant.unit_price
    assert sizes == {"Small": "85.00", "Medium": "120.00", "Large": "160.00"}


def test_no_seed_order_is_at_quill_and_pipkin():
    for order in load_seed_orders().SEED_ORDERS:
        assert "quill" not in order["catalog"]["store"]
        assert "Quill" not in order["store"]
        assert "Quill" not in order.get("order_at", "")
        assert "Quill" not in order["request"]


# ---- Check's copy of the store catalogs (/place-order prices from it) ----

STORE_CATALOGS_FILE = (
    Path(__file__).resolve().parents[2] / "check" / "backend" / "app" / "store_catalogs.py"
)


def load_store_catalogs():
    # plain data with no imports, like the seed orders
    spec = importlib.util.spec_from_file_location("store_catalogs", STORE_CATALOGS_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.STORE_CATALOGS


def test_checks_store_catalogs_match_the_real_stores():
    for store in load_store_catalogs():
        spec = fixture_spec(store["slug"])
        assert store["store"] == spec.merchant.name

        # every item the store sells, no more and no fewer
        listed_ids = []
        for item in store["items"]:
            listed_ids.append(item["item_id"])
        real_ids = []
        for item in spec.items:
            real_ids.append(item.id)
        assert listed_ids == real_ids, store["slug"]

        for listed in store["items"]:
            real = spec.find_item(listed["item_id"])
            assert listed["name"] == real.name
            assert listed["available"] == real.available

            # the first size is the item's own price, the rest are its variants in order
            sizes = listed["sizes"]
            assert sizes[0]["unit_price"] == real.unit_price, real.id
            # the page only names the first size in its price line, so it has to be in there
            if sizes[0]["label"] is not None:
                assert sizes[0]["label"].casefold() in real.source_quote.casefold(), real.id
            variants = []
            for variant in real.variants:
                variants.append({"label": variant.label, "unit_price": variant.unit_price})
            assert sizes[1:] == variants, real.id
