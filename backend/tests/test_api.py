# The whole thing through the HTTP API, with PayPal, Claude and the page fetch faked.

import copy
import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import connect, shop
from backend.app.config import Settings
from backend.app.db import create_tables, new_session
from backend.app.events import bus
from backend.app.fetcher import FetchError
from backend.app.main import create_app
from backend.tests.fakes import (
    FERNWOOD_SPEC,
    HOLLOWBROOK_SPEC,
    QUILL_SPEC,
    FakeAI,
    FakeClaude,
    FakePayPal,
    Reply,
    demo_page,
    text_block,
    tool_block,
)

SPECS = {
    "fernwood-thistle-goods": FERNWOOD_SPEC,
    "quill-pipkin-studio": QUILL_SPEC,
    "hollowbrook-bakery": HOLLOWBROOK_SPEC,
}
BAKERY_URL = "https://stores.example/hollowbrook-bakery/"


class World:
    # one test's app plus the fakes behind it
    def __init__(self, vault_id="vault-123", demo_mode="live"):
        self.paypal = FakePayPal()
        self.spec_overrides = {}
        self.repairs = {}
        self.fetched = []
        self.settings = Settings(
            _env_file=None,
            buyer_vault_id=vault_id,
            demo_mode=demo_mode,
            demo_stores_base_url="https://stores.example",
            # the test host doesn't resolve, the fetch itself is faked below
            fetch_allow_hosts="stores.example:443",
            anthropic_api_key="",
        )
        self.agent_claude = FakeClaude([])
        self.checked = []
        self.app = create_app(
            settings=self.settings, paypal=self.paypal, ai_factory=self.ai_factory,
            fetch=self.fetch, agent_client=self.agent_claude, order_reader=self.order_reader,
        )

    def slug(self, url):
        return url.rstrip("/").split("/")[-1]

    def fetch(self, url, allow_hosts=None):
        self.fetched.append(url)
        slug = self.slug(url)
        if slug not in SPECS:
            raise FetchError("The page answered 404")
        page = demo_page(slug)
        page.url = url
        page.final_url = url
        return page

    def ai_factory(self, settings):
        world = self

        class PerStoreAI:
            def extract_spec(self, page):
                slug = world.slug(page.url)
                data = world.spec_overrides.get(slug, SPECS[slug])
                self.inner = FakeAI(data, world.repairs)
                return self.inner.extract_spec(page)

            def repair_item(self, item, reason, page_text):
                return self.inner.repair_item(item, reason, page_text)

        return PerStoreAI()

    def order_reader(self, client_id, client_secret, paypal_order_id):
        self.checked.append(paypal_order_id)
        return {"status": "COMPLETED", "amount": "USD 12.00"}


@pytest.fixture
def world():
    create_tables()
    session = new_session()
    shop.wipe_everything(session)
    session.close()
    bus.clear()
    return World()


def wait_until_done(client, store_id):
    for _ in range(200):
        for store in client.get("/stores").json()["stores"]:
            if store["id"] == store_id and store["status"] != "connecting":
                return store
        time.sleep(0.02)
    raise AssertionError("The connect run never finished")


def wait_for_runs():
    for _ in range(200):
        if connect.runs_in_progress() == 0:
            return
        time.sleep(0.02)
    raise AssertionError("Connect runs never finished")


def connect_store(client, url=BAKERY_URL, mode=None):
    body = {"url": url}
    if mode:
        body["mode"] = mode
    response = client.post("/stores/connect", json=body)
    assert response.status_code == 202, response.text
    store_id = response.json()["store_id"]
    store = wait_until_done(client, store_id)
    wait_for_runs()
    return store_id, store


def read_events(client, store_id):
    response = client.get("/stores/" + str(store_id) + "/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = []
    for line in response.text.split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def test_connect_streams_the_run_and_the_store_goes_live(world):
    with TestClient(world.app) as client:
        store_id, store = connect_store(client)
        assert store["status"] == "live"
        assert store["merchant_name"] == "Hollowbrook Bakery"
        assert store["counts"] == {"verified": 4, "failed": 0, "unavailable": 1}

        events = read_events(client, store_id)
        types = [event["type"] for event in events]
        assert types[:4] == ["fetch.started", "fetch.done", "extract.started", "extract.done"]
        assert types[-1] == "store.ready"
        assert types.count("item.verified") == 4
        for event in events:
            assert event["store_id"] == store_id
            assert event["message"]
            assert event["data"]["fixture"] is False
        assert events[3]["data"]["item_count"] == 5
        assert events[-1]["data"]["counts"]["verified"] == 4


def test_catalog_only_has_verified_items(world):
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        catalog = client.get("/stores/" + str(store_id) + "/catalog").json()
        ids = [item["id"] for item in catalog["items"]]
        assert ids == ["sourdough-loaf", "seeded-rye", "cinnamon-morning-bun", "olive-focaccia"]
        assert catalog["shipping"]["amount"] == "6.00"
        # the sold out croissant is in the spec but not for sale
        spec = client.get("/stores/" + str(store_id) + "/spec").json()
        assert len(spec["spec"]["items"]) == 5
        assert "butter-croissant" not in spec["verified_item_ids"]
        assert "Butter Croissant is marked SOLD OUT, set available=false" in \
            spec["extraction_notes"]


def test_a_repair_shows_up_as_a_new_spec_version(world):
    wrong = copy.deepcopy(HOLLOWBROOK_SPEC)
    wrong["items"][1]["unit_price"] = "8.00"
    world.spec_overrides["hollowbrook-bakery"] = wrong
    world.repairs["seeded-rye"] = [
        (copy.deepcopy(HOLLOWBROOK_SPEC["items"][1]), "Used the current $7")
    ]
    with TestClient(world.app) as client:
        store_id, store = connect_store(client)
        assert store["counts"]["verified"] == 4
        spec = client.get("/stores/" + str(store_id) + "/spec").json()
        assert [version["version"] for version in spec["versions"]] == [1, 2]
        assert spec["versions"][0]["spec"]["items"][1]["unit_price"] == "8.00"
        assert spec["versions"][1]["spec"]["items"][1]["unit_price"] == "7.00"
        rye_runs = [run for run in spec["runs"] if run["item_id"] == "seeded-rye"]
        assert [run["ok"] for run in rye_runs] == [False, True]
        assert rye_runs[0]["page_check_ok"] is False
        assert rye_runs[0]["paypal_order_id"] is None
        types = [event["type"] for event in read_events(client, store_id)]
        assert "item.repairing" in types


def test_buy_computes_the_price_itself_and_captures(world):
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        response = client.post("/stores/" + str(store_id) + "/orders", json={
            "item_id": "sourdough-loaf", "variant_id": "half", "add_on_ids": ["sliced"],
            "quantity": 1,
        })
        assert response.status_code == 201, response.text
        order = response.json()
        assert order["total"] == "12.00"
        assert order["status"] == "captured"
        assert order["capture_id"].startswith("CAPTURE")
        assert order["description"] == "Sourdough Loaf (Half loaf) + Sliced"
        assert order["created_by"] == "manual"

        paid = world.paypal.created_bodies[-1]
        assert paid["payment_source"]["paypal"]["vault_id"] == "vault-123"
        assert paid["purchase_units"][0]["amount"]["value"] == "12.00"
        assert world.paypal.request_ids[-1]

        listed = client.get("/orders").json()["orders"]
        assert len(listed) == 1
        assert listed[0]["store_name"] == "Hollowbrook Bakery"


def test_a_client_sent_price_is_refused(world):
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        for extra in ({"price": "0.01"}, {"total": "0.01"}, {"unit_price": "0.01"}):
            body = {"item_id": "seeded-rye", "quantity": 1}
            body.update(extra)
            response = client.post("/stores/" + str(store_id) + "/orders", json=body)
            assert response.status_code == 422
        assert client.get("/orders").json()["orders"] == []


def test_buying_things_that_arent_for_sale(world):
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        path = "/stores/" + str(store_id) + "/orders"
        assert client.post(path, json={"item_id": "butter-croissant"}).status_code == 400
        assert client.post(path, json={"item_id": "bagel"}).status_code == 404
        assert client.post(path, json={"item_id": "seeded-rye", "quantity": 0}).status_code == 422
        assert client.post("/stores/999/orders", json={"item_id": "x"}).status_code == 404


def test_a_capture_that_isnt_completed_is_not_a_success(world):
    world.paypal.capture_status = "PENDING"
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        response = client.post("/stores/" + str(store_id) + "/orders",
                               json={"item_id": "seeded-rye"})
        assert response.status_code == 502
        listed = client.get("/orders").json()["orders"]
        assert listed[0]["status"] == "failed"
        assert "PENDING" in listed[0]["error"]


def test_no_vault_id_means_no_buying():
    create_tables()
    session = new_session()
    shop.wipe_everything(session)
    session.close()
    bus.clear()
    world = World(vault_id="")
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        response = client.post("/stores/" + str(store_id) + "/orders",
                               json={"item_id": "seeded-rye"})
        assert response.status_code == 503
        assert "BUYER_VAULT_ID" in response.json()["detail"]


def test_a_page_that_cant_be_fetched_fails_out_loud(world):
    with TestClient(world.app) as client:
        store_id, store = connect_store(client, "https://stores.example/not-a-store/")
        assert store["status"] == "failed"
        events = read_events(client, store_id)
        assert events[-1]["type"] == "error"
        assert "404" in events[-1]["message"]
        assert client.get("/stores/" + str(store_id) + "/catalog").status_code == 409


def test_a_store_where_nothing_verifies_is_not_live(world):
    wrong = copy.deepcopy(QUILL_SPEC)
    for item in wrong["items"]:
        item["unit_price"] = "1.00"
    world.spec_overrides["quill-pipkin-studio"] = wrong
    with TestClient(world.app) as client:
        store_id, store = connect_store(client, "https://stores.example/quill-pipkin-studio/")
        assert store["status"] == "failed"
        assert store["counts"] == {"verified": 0, "failed": 3, "unavailable": 0}
        response = client.post("/stores/" + str(store_id) + "/orders",
                               json={"item_id": "headshot"})
        assert response.status_code == 409


def test_private_urls_are_refused_before_anything_starts(world):
    with TestClient(world.app) as client:
        for url in ("http://127.0.0.1:8000/", "http://169.254.169.254/latest/",
                    "file:///etc/passwd", "ftp://stores.example/"):
            response = client.post("/stores/connect", json={"url": url})
            assert response.status_code == 400, url
        assert client.get("/stores").json()["stores"] == []
        assert world.fetched == []


def test_replay_without_a_fixture_fails_and_never_fetches(world):
    with TestClient(world.app) as client:
        store_id, store = connect_store(
            client, "https://stores.example/never-recorded/", mode="replay"
        )
        assert store["status"] == "failed"
        assert store["mode"] == "replay"
        events = read_events(client, store_id)
        assert events[-1]["type"] == "error"
        assert "fixture" in events[-1]["message"]
        assert world.fetched == []


def test_demo_reset_wipes_and_reconnects_the_three_stores(world):
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        client.post("/stores/" + str(store_id) + "/orders", json={"item_id": "seeded-rye"})

        response = client.post("/demo/reset", json={})
        assert response.status_code == 202
        started = response.json()["stores"]
        assert len(started) == 3
        for one in started:
            wait_until_done(client, one["store_id"])
        wait_for_runs()

        stores = client.get("/stores").json()["stores"]
        names = [store["merchant_name"] for store in stores]
        assert names == ["Fernwood & Thistle Goods", "Quill & Pipkin Studio",
                         "Hollowbrook Bakery"]
        for store in stores:
            assert store["status"] == "live"
        assert client.get("/orders").json()["orders"] == []


def test_the_agent_buys_through_the_same_code_and_reports_its_steps(world):
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)

        def check_after_buying(request):
            # the order id comes out of the buy_item result Claude was just sent
            result = json.loads(request["messages"][-1]["content"][0]["content"])
            return Reply([tool_block(
                "check_payment", {"paypal_order_id": result["paypal_order_id"]}, "c4"
            )], "tool_use")

        world.agent_claude.replies = [
            Reply([tool_block("list_stores", {}, "c1")], "tool_use"),
            Reply([tool_block("search_catalog", {"store_id": store_id, "query": "sourdough"},
                              "c2")], "tool_use"),
            Reply([tool_block("buy_item", {
                "store_id": store_id, "item_id": "sourdough-loaf", "variant_id": "half",
                "add_on_ids": ["sliced"], "quantity": 1,
            }, "c3")], "tool_use"),
            check_after_buying,
            Reply([text_block("Bought a sliced half sourdough loaf for $12.00.")]),
        ]
        response = client.post("/agent/chat", json={"messages": [{
            "role": "user",
            "content": "Get me a half sourdough loaf, sliced, from Hollowbrook Bakery.",
        }]})
        assert response.status_code == 200, response.text
        answer = response.json()
        assert [step["tool"] for step in answer["steps"]] == [
            "list_stores", "search_catalog", "buy_item", "check_payment",
        ]
        assert answer["steps"][0]["output"]["stores"][0]["name"] == "Hollowbrook Bakery"
        searched = answer["steps"][1]["output"]["items"]
        assert [item["id"] for item in searched] == ["sourdough-loaf"]
        bought = answer["steps"][2]["output"]
        assert bought["status"] == "captured"
        assert bought["total"] == "12.00"
        assert answer["orders"][0]["created_by"] == "agent"
        assert world.checked == [bought["paypal_order_id"]]
        assert "12.00" in answer["reply"]

        # each tool result went back to Claude in one user message
        last_request = world.agent_claude.requests[-1]
        assert last_request["messages"][-1]["content"][0]["type"] == "tool_result"
        listed = client.get("/orders").json()["orders"]
        assert listed[0]["created_by"] == "agent"
        assert listed[0]["capture_id"] == bought["capture_id"]


def test_the_agent_is_told_when_a_purchase_fails(world):
    with TestClient(world.app) as client:
        store_id, _store = connect_store(client)
        world.agent_claude.replies = [
            Reply([tool_block("buy_item", {
                "store_id": store_id, "item_id": "butter-croissant", "quantity": 1,
            })], "tool_use"),
            Reply([text_block("The croissant is sold out.")]),
        ]
        answer = client.post("/agent/chat", json={"messages": [{
            "role": "user", "content": "Buy a croissant",
        }]}).json()
        assert answer["steps"][0]["is_error"] is True
        assert "available" in answer["steps"][0]["output"]["error"]
        sent_back = world.agent_claude.requests[-1]["messages"][-1]["content"][0]
        assert sent_back["is_error"] is True
        assert answer["orders"] == []


def test_config_says_what_is_set_without_leaking_it(world):
    with TestClient(world.app) as client:
        config = client.get("/config").json()
        assert config["vault_configured"] is True
        assert config["claude_configured"] is False
        assert config["default_mode"] == "live"
        assert len(config["demo_store_urls"]) == 3
        assert "vault-123" not in json.dumps(config)
