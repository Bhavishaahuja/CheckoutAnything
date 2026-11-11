# Reset demo makes the Hollowbrook demo store fully live, so every starter prompt on the Agent page
# finds something to buy. The other demo stores keep their flags for the merchant to review.

import pytest
from fastapi.testclient import TestClient

from backend.app import review
from backend.tests.test_api import (  # noqa: F401 (world is a fixture)
    BAKERY_URL,
    connect_store,
    wait_for_runs,
    wait_until_done,
    world,
)

SOURDOUGH = {"item_id": "sourdough-loaf", "variant_id": "half", "add_on_ids": ["sliced"]}


@pytest.fixture
def publish_bakery(monkeypatch):
    monkeypatch.setattr(review, "PUBLISHED_ON_CONNECT", {"hollowbrook-bakery"})


def test_every_verified_bakery_item_goes_live_on_connect(world, publish_bakery):  # noqa: F811
    with TestClient(world.app) as client:
        store_id, store = connect_store(client)

        catalog = client.get("/stores/" + str(store_id) + "/catalog").json()
        live_ids = [item["id"] for item in catalog["items"]]
        # the flagged sourdough and rye are live too, the sold out croissant never is
        assert "sourdough-loaf" in live_ids
        assert "seeded-rye" in live_ids
        assert "butter-croissant" not in live_ids

        # the counts the Agent page sidebar shows: live equals verified
        listed = client.get("/stores").json()["stores"][0]
        assert listed["counts"]["live"] == listed["counts"]["verified"] == len(live_ids)

        # nothing on it waits for a look, so the review counter is clear
        payload = client.get("/stores/" + str(store_id) + "/review").json()
        for item in payload["items"]:
            if item["item_id"] in live_ids:
                assert item["published"] is True

        # the starter prompt's order goes through
        bought = client.post("/stores/" + str(store_id) + "/orders", json=SOURDOUGH)
        assert bought.status_code == 201, bought.text


def test_without_the_demo_rule_flagged_items_wait_and_the_count_says_so(world):  # noqa: F811
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        listed = client.get("/stores").json()["stores"][0]
        # "2 of 4 live" on the sidebar
        assert listed["counts"]["live"] < listed["counts"]["verified"]
        # the rye has a field to look at, so it can't be bought until the merchant confirms it
        rye = {"item_id": "seeded-rye"}
        refused = client.post("/stores/" + str(store_id) + "/orders", json=rye)
        assert refused.status_code == 409


def test_reset_demo_leaves_every_starter_store_with_something_to_buy(world, publish_bakery):  # noqa: F811
    with TestClient(world.app) as client:
        started = client.post("/demo/reset", json={}).json()["stores"]
        for one in started:
            wait_until_done(client, one["store_id"])
        wait_for_runs()

        live_by_name = {}
        for store in client.get("/stores").json()["stores"]:
            live_by_name[store["merchant_name"]] = store["counts"]["live"]
        # the bakery is whole, so the sourdough prompt works. the Agent page only offers a
        # "What can I buy at" prompt for a store whose live count is above zero
        assert live_by_name["Hollowbrook Bakery"] == 4
        assert live_by_name["Fernwood & Thistle Goods"] > 0
        bakery_id = started[1]["store_id"]
        bought = client.post("/stores/" + str(bakery_id) + "/orders", json=SOURDOUGH)
        assert bought.status_code == 201, bought.text


def test_the_agent_is_told_how_many_items_it_can_buy(world, publish_bakery):  # noqa: F811
    with TestClient(world.app) as client:
        connect_store(client, BAKERY_URL)
        from backend.app.agent import ShoppingAgent
        from backend.app.db import new_session

        session = new_session()
        try:
            agent = ShoppingAgent(session, world.paypal, world.settings, client=world.agent_claude)
            stores = agent.tool_list_stores()
        finally:
            session.close()
        assert stores[0]["live_items"] == 4
        assert "verified_items" not in stores[0]
