# The merchant's review of a connected store, through the HTTP API: flags with reasons,
# confirming, editing (with the PayPal check), publishing, ordering, renaming columns and stock.

import copy

from fastapi.testclient import TestClient

from backend.app.paypal_client import PayPalError
from backend.tests.fakes import HOLLOWBROOK_SPEC
from backend.tests.test_api import connect_store, world  # noqa: F401


def review(client, store_id):
    response = client.get("/stores/" + str(store_id) + "/review")
    assert response.status_code == 200, response.text
    return response.json()


def item_of(payload, item_id):
    for item in payload["items"]:
        if item["item_id"] == item_id:
            return item
    raise AssertionError("no item " + item_id)


def flag_of(payload, item_id, field):
    for flag in item_of(payload, item_id)["flags"]:
        if flag["field"] == field:
            return flag
    return None


def patch(client, store_id, item_id, body):
    return client.patch("/stores/" + str(store_id) + "/items/" + item_id, json=body)


def catalog_ids(client, store_id):
    catalog = client.get("/stores/" + str(store_id) + "/catalog").json()
    return [item["id"] for item in catalog["items"]]


def test_every_flag_has_a_reason_and_clean_items_go_live(world):  # noqa: F811
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        payload = review(client, store_id)

        # rye: a crossed-out price in the quote, and Claude's own note about it
        rye = flag_of(payload, "seeded-rye", "unit_price")
        assert rye["resolved"] is False
        assert any("$8.00 crossed out" in reason for reason in rye["reasons"])
        assert any(reason.startswith("Claude's note:") for reason in rye["reasons"])
        # focaccia: the footnote note. croissant: the sold out note, on availability
        assert flag_of(payload, "olive-focaccia", "unit_price")["reasons"]
        assert flag_of(payload, "butter-croissant", "available")["reasons"]
        assert payload["needs_look"] == 3
        for item in payload["items"]:
            for flag in item["flags"]:
                assert flag["reasons"] and all(flag["reasons"])

        # nothing to look at: live straight away. flagged: held back
        assert item_of(payload, "sourdough-loaf")["published"] is True
        assert item_of(payload, "sourdough-loaf")["flags"] == []
        assert item_of(payload, "seeded-rye")["published"] is False
        assert "needs a look" in item_of(payload, "seeded-rye")["blocked_reason"]
        assert item_of(payload, "seeded-rye")["checked_at"]


def test_a_repaired_price_is_flagged_with_the_failure_that_caused_it(world):  # noqa: F811
    wrong = copy.deepcopy(HOLLOWBROOK_SPEC)
    wrong["items"][3]["unit_price"] = "4.00"
    world.spec_overrides["hollowbrook-bakery"] = wrong
    world.repairs["cinnamon-morning-bun"] = [
        (copy.deepcopy(HOLLOWBROOK_SPEC["items"][3]), "Used the price on the page")
    ]
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        flag = flag_of(review(client, store_id), "cinnamon-morning-bun", "unit_price")
        assert "first read $4.00, then repaired it to $4.50" in flag["reasons"][0]
        assert "The page says 4.50 but the spec says 4.00" in flag["reasons"][0]


def test_a_flagged_item_cant_be_published_until_it_is_confirmed(world):  # noqa: F811
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        path = "/stores/" + str(store_id) + "/publish"

        blocked = client.post(path, json={"item_ids": ["sourdough-loaf", "seeded-rye"]})
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["blocked"][0]["item_id"] == "seeded-rye"
        assert patch(client, store_id, "seeded-rye", {"published": True}).status_code == 409
        buy = client.post("/stores/" + str(store_id) + "/orders", json={"item_id": "seeded-rye"})
        assert buy.status_code == 409
        assert "hasn't published" in buy.json()["detail"]

        confirmed = patch(client, store_id, "seeded-rye", {"resolve": ["unit_price"]})
        assert confirmed.status_code == 200
        assert confirmed.json()["needs_look"] == 2
        assert flag_of(confirmed.json(), "seeded-rye", "unit_price")["resolved"] is True

        published = client.post(path, json={"item_ids": ["seeded-rye"]})
        assert published.status_code == 200
        assert "seeded-rye" in catalog_ids(client, store_id)
        buy = client.post("/stores/" + str(store_id) + "/orders", json={"item_id": "seeded-rye"})
        assert buy.status_code == 201

        # the sold out croissant can be confirmed but never published
        assert patch(client, store_id, "butter-croissant", {"resolve": ["available"]}) \
            .status_code == 200
        refused = client.post(path, json={"item_ids": ["butter-croissant"]})
        assert refused.status_code == 409


def test_a_price_edit_is_checked_at_paypal_and_undo_restores_everything(world):  # noqa: F811
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        orders_before = len(world.paypal.orders)

        edited = patch(client, store_id, "seeded-rye", {"unit_price": "7.5"})
        assert edited.status_code == 200, edited.text
        # correcting a flagged field settles it
        assert flag_of(edited.json(), "seeded-rye", "unit_price")["resolved"] is True
        assert len(world.paypal.orders) == orders_before + 1
        assert world.paypal.created_bodies[-1]["purchase_units"][0]["amount"]["value"] == "7.50"

        spec = client.get("/stores/" + str(store_id) + "/spec").json()
        assert spec["spec"]["items"][1]["unit_price"] == "7.50"
        assert spec["versions"][-1]["note"].startswith("Merchant edit of Seeded Rye")
        run = [run for run in spec["runs"] if run["item_id"] == "seeded-rye"][-1]
        # honest about it: PayPal agreed, the page didn't back this price
        assert run["ok"] is True and run["paypal_check_ok"] is True
        assert run["page_check_ok"] is False
        assert "the page check last passed at $7.00" in run["reason"]

        # a second edit keeps it settled
        again = patch(client, store_id, "seeded-rye", {"unit_price": "7.25"})
        assert flag_of(again.json(), "seeded-rye", "unit_price")["resolved"] is True

        # the undo: the agent's price again, so the flag comes back by itself
        undone = patch(client, store_id, "seeded-rye", {"unit_price": "7.00"})
        assert undone.status_code == 200
        assert flag_of(undone.json(), "seeded-rye", "unit_price")["resolved"] is False
        assert undone.json()["needs_look"] == 3
        spec = client.get("/stores/" + str(store_id) + "/spec").json()
        assert spec["spec"]["items"][1]["unit_price"] == "7.00"
        run = [run for run in spec["runs"] if run["item_id"] == "seeded-rye"][-1]
        assert run["page_check_ok"] is True and run["reason"] is None


def test_bad_edits_change_nothing(world):  # noqa: F811
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        versions = len(client.get("/stores/" + str(store_id) + "/spec").json()["versions"])
        for bad in ("-3", "0", "", "  ", "abc", "4.999", "nan"):
            assert patch(client, store_id, "sourdough-loaf", {"unit_price": bad}) \
                .status_code == 422, bad
        assert patch(client, store_id, "sourdough-loaf", {"name": "  "}).status_code == 422
        assert patch(client, store_id, "sourdough-loaf", {"stock": -1}).status_code == 422
        assert patch(client, store_id, "sourdough-loaf", {"category": "Weapons"}) \
            .status_code == 422
        assert patch(client, store_id, "sourdough-loaf", {"resolve": ["stock"]}) \
            .status_code == 422
        assert patch(client, store_id, "bagel", {"stock": 1}).status_code == 404
        assert patch(client, store_id, "sourdough-loaf", {"price": "1.00"}).status_code == 422

        # PayPal refusing the new price means the edit isn't saved
        world.paypal.fail_with = PayPalError(503, name="SERVICE_UNAVAILABLE", message="down")
        assert patch(client, store_id, "sourdough-loaf", {"unit_price": "10.00"}) \
            .status_code == 502
        world.paypal.fail_with = None

        spec = client.get("/stores/" + str(store_id) + "/spec").json()
        assert len(spec["versions"]) == versions
        assert spec["spec"]["items"][0]["unit_price"] == "9.00"
        assert item_of(review(client, store_id), "sourdough-loaf")["published"] is True


def test_description_category_and_stock(world):  # noqa: F811
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        orders_before = len(world.paypal.orders)
        response = patch(client, store_id, "sourdough-loaf", {
            "description": "Baked every morning", "category": "Food and drink", "stock": 2,
        })
        assert response.status_code == 200, response.text
        # a description never reaches the PayPal check
        assert len(world.paypal.orders) == orders_before
        item = item_of(response.json(), "sourdough-loaf")
        assert item["category"] == "Food and drink" and item["stock"] == 2

        catalog = client.get("/stores/" + str(store_id) + "/catalog").json()
        assert catalog["items"][0]["description"] == "Baked every morning"
        assert catalog["items"][0]["category"] == "Food and drink"

        path = "/stores/" + str(store_id) + "/orders"
        too_many = client.post(path, json={"item_id": "sourdough-loaf", "quantity": 3})
        assert too_many.status_code == 409
        assert "Only 2" in too_many.json()["detail"]
        assert client.post(path, json={"item_id": "sourdough-loaf", "quantity": 2}) \
            .status_code == 201
        assert item_of(review(client, store_id), "sourdough-loaf")["stock"] == 0
        sold_out = client.post(path, json={"item_id": "sourdough-loaf"})
        assert sold_out.status_code == 409
        assert "out of stock" in sold_out.json()["detail"]

        # null clears it: stock isn't tracked again
        assert patch(client, store_id, "sourdough-loaf", {"stock": None}).status_code == 200
        assert client.post(path, json={"item_id": "sourdough-loaf"}).status_code == 201


def test_the_catalog_follows_the_merchants_order(world):  # noqa: F811
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        assert catalog_ids(client, store_id) == ["sourdough-loaf", "cinnamon-morning-bun"]
        path = "/stores/" + str(store_id) + "/order"
        new_order = ["cinnamon-morning-bun", "olive-focaccia", "butter-croissant",
                     "sourdough-loaf", "seeded-rye"]
        response = client.put(path, json={"item_ids": new_order})
        assert response.status_code == 200, response.text
        assert [item["item_id"] for item in response.json()["items"]] == new_order
        assert catalog_ids(client, store_id) == ["cinnamon-morning-bun", "sourdough-loaf"]

        assert client.put(path, json={"item_ids": new_order[:3]}).status_code == 422
        assert client.put(path, json={"item_ids": new_order[:4] + ["bagel"]}).status_code == 422


def test_renaming_a_column_persists_and_reaches_the_catalog(world):  # noqa: F811
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        path = "/stores/" + str(store_id) + "/columns/"
        response = client.put(path + "unit_price", json={"label": "  Cost  "})
        assert response.status_code == 200, response.text
        column = [entry for entry in response.json()["columns"]
                  if entry["field"] == "unit_price"][0]
        assert column["label"] == "Cost" and column["default_label"] == "Price"
        assert column["paypal_field"] == "purchase_units[0].items[0].unit_amount.value"
        catalog = client.get("/stores/" + str(store_id) + "/catalog").json()
        assert catalog["field_labels"]["unit_price"] == "Cost"

        # blank puts the default back
        response = client.put(path + "unit_price", json={"label": ""})
        column = [entry for entry in response.json()["columns"]
                  if entry["field"] == "unit_price"][0]
        assert column["label"] == "Price"
        assert client.put(path + "nope", json={"label": "x"}).status_code == 404
        assert client.put(path + "name", json={"label": "x" * 41}).status_code == 422


def test_an_edit_can_rescue_an_item_that_failed(world):  # noqa: F811
    # nothing on this page backs 99.00, so every item fails and the store isn't live
    wrong = copy.deepcopy(HOLLOWBROOK_SPEC)
    wrong["items"] = [copy.deepcopy(HOLLOWBROOK_SPEC["items"][0])]
    wrong["items"][0]["unit_price"] = "99.00"
    world.spec_overrides["hollowbrook-bakery"] = wrong
    with TestClient(world.app) as client:
        store_id, store = connect_store(client)
        assert store["status"] == "failed"
        assert item_of(review(client, store_id), "sourdough-loaf")["published"] is False

        fixed = patch(client, store_id, "sourdough-loaf", {"unit_price": "9.00"})
        assert fixed.status_code == 200, fixed.text
        stores = client.get("/stores").json()["stores"]
        assert stores[0]["status"] == "live" and stores[0]["counts"]["verified"] == 1
        # verified now, but going live is still the merchant's call
        assert catalog_ids(client, store_id) == []
        assert patch(client, store_id, "sourdough-loaf", {"published": True}).status_code == 200
        assert catalog_ids(client, store_id) == ["sourdough-loaf"]


def test_undoing_an_edit_on_a_live_item_takes_it_down_again(world):  # noqa: F811
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        assert patch(client, store_id, "seeded-rye", {"unit_price": "7.50"}).status_code == 200
        assert patch(client, store_id, "seeded-rye", {"published": True}).status_code == 200
        assert "seeded-rye" in catalog_ids(client, store_id)
        # back to the price the agent wasn't sure about: amber again, and not for sale
        undone = patch(client, store_id, "seeded-rye", {"unit_price": "7.00"})
        assert item_of(undone.json(), "seeded-rye")["published"] is False
        assert "seeded-rye" not in catalog_ids(client, store_id)

        # a confirmed field stays confirmed whatever is typed into it afterwards
        assert patch(client, store_id, "seeded-rye", {"resolve": ["unit_price"]}) \
            .status_code == 200
        assert patch(client, store_id, "seeded-rye", {"unit_price": "7.50"}).status_code == 200
        back = patch(client, store_id, "seeded-rye", {"unit_price": "7.00"})
        assert flag_of(back.json(), "seeded-rye", "unit_price")["resolved"] is True
