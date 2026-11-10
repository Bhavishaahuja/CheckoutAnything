# Agent orders through Check (CHECK_URL set), with the Check service faked. The tests in
# test_api.py are the other path, the flag unset, and none of them changed.

import json

import pytest
import responses
from fastapi.testclient import TestClient

from backend.app import check_client, shop
from backend.app.check_client import CheckClient, CheckError
from backend.app.config import Settings
from backend.app.db import add_missing_order_columns, create_tables, make_engine, new_session
from backend.app.events import bus
from backend.tests.fakes import FakeCheck, Reply, text_block, tool_block
from backend.tests.test_api import World, connect_store

REQUEST = "Get me a half sourdough loaf, sliced, from Hollowbrook Bakery. No more than $15."
CHECK = "https://check.example"
MISMATCH = {"verdict": "mismatch", "risk_score": 85,
            "reason": "Ordered a whole loaf, mandate says half"}


def fresh(check, **options):
    create_tables()
    session = new_session()
    shop.wipe_everything(session)
    session.close()
    bus.clear()
    return World(check=check, **options)


@pytest.fixture
def check():
    return FakeCheck()


@pytest.fixture
def world(check):
    return fresh(check, check_frontend_url="https://check-app.example")


def agent_buys(world, client, store_id, request=REQUEST, variant_id="half"):
    buy = {"store_id": store_id, "item_id": "sourdough-loaf", "add_on_ids": ["sliced"],
           "quantity": 1}
    if variant_id:
        buy["variant_id"] = variant_id
    world.agent_claude.replies = [
        Reply([tool_block("buy_item", buy, "c1")], "tool_use"),
        Reply([text_block("Done.")]),
    ]
    response = client.post("/agent/chat", json={"messages": [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hi, what should I buy?"},
        {"role": "user", "content": request},
    ]})
    assert response.status_code == 200, response.text
    return response.json()


def test_an_agent_order_goes_to_check_and_comes_back_captured(world, check):
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        paypal_orders_before = len(world.paypal.created_bodies)

        answer = agent_buys(world, client, store_id)

        # the human's own last message, word for word, with the store as the merchant
        assert len(check.mandates) == 1
        assert check.mandates[0]["raw_request"] == REQUEST
        assert check.mandates[0]["merchant"] == "Hollowbrook Bakery"

        # the priced order: item with its add-on, the variant as size, price from the spec
        assert check.sent_orders == [{
            "mandate_id": 1,
            "items": [{"name": "Sourdough Loaf + Sliced", "size": "Half loaf", "quantity": 1,
                       "unit_price": "6.00"}],
            "shipping": "6.00",
            "vault_id": "vault-123",
            "merchant": "Hollowbrook Bakery",
        }]

        # nothing was paid or captured here, Check did that
        assert len(world.paypal.created_bodies) == paypal_orders_before

        bought = answer["steps"][0]["output"]
        assert answer["steps"][0]["is_error"] is False
        assert bought["status"] == "captured"
        assert bought["review_state"] == "auto_approved"
        assert bought["total"] == "12.00"
        # the agent is never told why, only where the order stands
        assert "reason" not in json.dumps(bought)
        sent_to_claude = world.agent_claude.requests[-1]["messages"][-1]["content"][0]
        assert "Matches the mandate" not in sent_to_claude["content"]
        assert "Matches the mandate" not in json.dumps(answer["steps"])

        order = client.get("/orders").json()["orders"][0]
        assert order["created_by"] == "agent"
        assert order["status"] == "captured"
        assert order["check_order_id"] == 41
        assert order["check_mandate_id"] == 1
        assert order["review_state"] == "auto_approved"
        assert order["check_verdict"] == "match"
        assert order["check_reason"] == "Matches the mandate."
        assert order["decision_ms"] is None
        assert order["paypal_order_id"] == "CHECKORDER0000000041"
        assert order["capture_id"] == "CHECKCAPTURE0000000041"


def test_an_order_check_holds_waits_for_the_human_then_updates(world, check):
    check.decide = ("authorized", "needs_review", MISMATCH)
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        answer = agent_buys(world, client, store_id, variant_id=None)

        # on hold is not an error and not a purchase
        assert answer["steps"][0]["is_error"] is False
        assert answer["steps"][0]["output"]["status"] == "authorized"
        assert answer["steps"][0]["output"]["review_state"] == "needs_review"
        assert answer["steps"][0]["output"]["capture_id"] is None
        assert "whole loaf" not in json.dumps(answer["steps"])

        order = client.get("/orders").json()["orders"][0]
        assert order["status"] == "authorized"
        assert order["review_state"] == "needs_review"
        assert order["check_verdict"] == "mismatch"
        assert order["check_reason"] == "Ordered a whole loaf, mandate says half"
        assert order["capture_id"] is None

        link = client.post("/orders/" + str(order["id"]) + "/review-link")
        assert link.status_code == 201, link.text
        assert link.json()["url"] == "https://check-app.example/confirm/token-41-1"

        # the human approves on the confirm page. the next read of the grid has it
        check.human_decides(41, "approve", 4200)
        order = client.get("/orders").json()["orders"][0]
        assert order["status"] == "captured"
        assert order["review_state"] == "approved"
        assert order["decision_ms"] == 4200
        assert order["capture_id"] == "CHECKCAPTURE0000000041"

        # finished orders aren't asked about again
        calls = check.list_calls
        client.get("/orders")
        assert check.list_calls == calls
        # and there's nothing left to review
        assert client.post("/orders/" + str(order["id"]) + "/review-link").status_code == 409


def test_a_rejected_order_ends_up_voided(world, check):
    check.decide = ("authorized", "needs_review", MISMATCH)
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        agent_buys(world, client, store_id, variant_id=None)
        check.human_decides(41, "reject", 9000)
        order = client.get("/orders").json()["orders"][0]
        assert order["status"] == "voided"
        assert order["review_state"] == "rejected"
        assert order["capture_id"] is None


def test_the_system_prompt_only_mentions_the_hold_when_check_is_on(world, check):
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        agent_buys(world, client, store_id)
        assert "needs_review" in world.agent_claude.requests[0]["system"]


def test_two_buys_at_one_store_in_one_chat_share_a_mandate(world, check):
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        buy = {"store_id": store_id, "item_id": "seeded-rye", "quantity": 1}
        world.agent_claude.replies = [
            Reply([tool_block("buy_item", buy, "c1"), tool_block("buy_item", buy, "c2")],
                  "tool_use"),
            Reply([text_block("Done.")]),
        ]
        client.post("/agent/chat", json={"messages": [{"role": "user", "content": "Two ryes"}]})
        assert len(check.mandates) == 1
        assert [sent["mandate_id"] for sent in check.sent_orders] == [1, 1]


def test_something_that_cant_be_bought_never_reaches_check(world, check):
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        world.agent_claude.replies = [
            Reply([tool_block("buy_item", {
                "store_id": store_id, "item_id": "butter-croissant", "quantity": 1,
            })], "tool_use"),
            Reply([text_block("Sold out.")]),
        ]
        answer = client.post("/agent/chat", json={"messages": [
            {"role": "user", "content": "Buy a croissant"},
        ]}).json()
        assert answer["steps"][0]["is_error"] is True
        assert check.mandates == []
        assert check.sent_orders == []


def test_check_failing_is_reported_and_nothing_is_charged_here(world, check):
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        paypal_orders_before = len(world.paypal.created_bodies)

        check.fail_mandate = CheckError("Couldn't parse the request", 502)
        answer = agent_buys(world, client, store_id)
        assert answer["steps"][0]["is_error"] is True
        assert "Couldn't parse the request" in answer["steps"][0]["output"]["error"]
        assert client.get("/orders").json()["orders"] == []

        check.fail_mandate = None
        check.fail_order = CheckError("PayPal create order failed", 502)
        answer = agent_buys(world, client, store_id)
        assert answer["steps"][0]["is_error"] is True
        order = client.get("/orders").json()["orders"][0]
        assert order["status"] == "failed"
        assert order["error"] == "Check: PayPal create order failed"
        assert order["check_order_id"] is None

        # it never falls back to paying here behind Check's back
        assert len(world.paypal.created_bodies) == paypal_orders_before


def test_a_hold_for_the_wrong_amount_is_flagged(world, check):
    check.held_total = "13.00"
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        answer = agent_buys(world, client, store_id)
        assert answer["steps"][0]["is_error"] is True
        assert "13.00" in answer["steps"][0]["output"]["error"]


def test_a_manual_test_buy_still_pays_here(world, check):
    # there's no human request to check a manual buy against, so it takes the old road
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        response = client.post("/stores/" + str(store_id) + "/orders", json={
            "item_id": "seeded-rye", "quantity": 1,
        })
        assert response.status_code == 201
        assert response.json()["status"] == "captured"
        assert response.json()["check_order_id"] is None
        assert check.sent_orders == []


def test_without_the_merchant_key_orders_still_go_through(check):
    check.can_read = False
    world = fresh(check)
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        agent_buys(world, client, store_id)
        order = client.get("/orders").json()["orders"][0]
        assert order["status"] == "captured"
        assert order["check_verdict"] is None
        assert client.get("/config").json()["check_configured"] is True
        assert client.get("/config").json()["check_merchant_configured"] is False
        assert client.get("/disputes").status_code == 503
        assert client.post("/orders/" + str(order["id"]) + "/review-link").status_code == 503


def test_disputes_pass_through_to_check(world, check):
    with TestClient(world.app) as client:
        assert client.get("/disputes").json()["disputes"][0]["paypal_dispute_id"] == \
            "PP-R-ABC-10001234"
        assert client.post("/disputes/sync").json()["created"] == 1
        assert client.get("/disputes/3/evidence").json()["summary"] == "The buyer asked."
        assert client.post("/disputes/3/redraft").status_code == 200
        assert client.get("/disputes/9/evidence").status_code == 404
        refused = client.post("/disputes/3/submit-evidence")
        assert refused.status_code == 409
        assert refused.json()["detail"] == "Evidence was already submitted"


# ---- the flag unset ----


def test_with_no_check_url_nothing_about_check_is_on():
    assert check_client.client_from_settings(Settings(_env_file=None, check_url="")) is None

    world = fresh(None)
    with TestClient(world.app) as client:
        config = client.get("/config").json()
        assert config["check_configured"] is False
        assert config["check_review_links"] is False
        assert client.get("/disputes").status_code == 503

        store_id, _store = connect_store(client)
        agent_buys(world, client, store_id)
        # paid and captured here, exactly as before
        order = client.get("/orders").json()["orders"][0]
        assert order["status"] == "captured"
        assert order["capture_id"].startswith("CAPTURE")
        assert order["check_order_id"] is None
        assert order["review_state"] is None
        assert "needs_review" not in world.agent_claude.requests[0]["system"]
        assert client.post("/orders/" + str(order["id"]) + "/review-link").status_code == 503


def test_the_flag_builds_a_client_with_both_keys():
    settings = Settings(_env_file=None, check_url=CHECK + "/", check_agent_key="agent-key",
                        check_merchant_key="merchant-key")
    client = check_client.client_from_settings(settings)
    assert client.base_url == CHECK
    assert client.can_read is True


# ---- the HTTP client, against the shapes in check/docs/api.md ----


@responses.activate
def test_the_client_sends_each_key_to_its_own_side():
    responses.post(CHECK + "/mandates", status=201, json={"id": 7})
    responses.post(CHECK + "/orders", status=201, json={
        "id": 42, "status": "authorized", "review_state": "needs_review", "total": "12.00",
    })
    responses.get(CHECK + "/orders/42", json={"id": 42, "status": "authorized"})
    responses.post(CHECK + "/orders/42/review-link", status=201,
                   json={"review_token": "kL0x", "expires_at": "2026-12-03T01:56:55Z"})
    client = CheckClient(CHECK, "agent-key", "merchant-key")

    assert client.create_mandate("A half loaf", "Hollowbrook Bakery", "Sam")["id"] == 7
    placed = client.create_order(7, [{"name": "Loaf", "quantity": 1, "unit_price": "6.00"}],
                                 "6.00", "vault-1", "Hollowbrook Bakery")
    assert placed["review_state"] == "needs_review"
    client.get_order(42)
    assert client.create_review_link(42)["review_token"] == "kL0x"

    keys = [call.request.headers["X-API-Key"] for call in responses.calls]
    assert keys == ["agent-key", "agent-key", "merchant-key", "merchant-key"]
    assert json.loads(responses.calls[0].request.body) == {
        "buyer_label": "Sam", "request_text": "A half loaf", "merchant": "Hollowbrook Bakery",
    }
    assert json.loads(responses.calls[1].request.body) == {
        "mandate_id": 7,
        "items": [{"name": "Loaf", "quantity": 1, "unit_price": "6.00"}],
        "shipping": "6.00",
        "vault_id": "vault-1",
        "merchant": "Hollowbrook Bakery",
    }


@responses.activate
def test_the_client_turns_checks_errors_into_one_kind_of_error():
    responses.get(CHECK + "/orders/1", status=404, json={"detail": "Order 1 not found"})
    responses.post(CHECK + "/orders/2/review-link", status=409, json={"detail": {
        "message": "The order isn't waiting for review", "status": "captured",
    }})
    responses.get(CHECK + "/disputes", status=401, json={"detail": "Invalid or missing key"})
    client = CheckClient(CHECK, "agent-key", "merchant-key")

    with pytest.raises(CheckError) as not_found:
        client.get_order(1)
    assert not_found.value.status_code == 404
    assert str(not_found.value) == "Order 1 not found"

    with pytest.raises(CheckError) as conflict:
        client.create_review_link(2)
    assert conflict.value.status_code == 409
    assert str(conflict.value) == "The order isn't waiting for review"

    with pytest.raises(CheckError) as unauthorized:
        client.list_disputes()
    assert unauthorized.value.status_code == 401

    # nothing listening at all
    with pytest.raises(CheckError) as unreachable:
        client.sync_disputes()
    assert unreachable.value.status_code == 0


def test_a_missing_key_is_refused_before_any_call():
    with pytest.raises(CheckError) as missing:
        CheckClient(CHECK, "agent-key", "").get_order(1)
    assert missing.value.status_code == 503


# ---- an orders table from before the Check columns ----


def test_an_old_orders_table_gets_the_new_columns():
    engine = make_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, status VARCHAR(20))"
        )
        connection.exec_driver_sql("INSERT INTO orders (id, status) VALUES (1, 'captured')")

    add_missing_order_columns(engine)
    # twice is fine, the second run finds nothing to add
    add_missing_order_columns(engine)

    with engine.begin() as connection:
        row = connection.exec_driver_sql(
            "SELECT status, check_order_id, review_state, decision_ms FROM orders"
        ).one()
    assert tuple(row) == ("captured", None, None, None)
