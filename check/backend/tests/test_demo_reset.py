# POST /demo/reset: void every open hold, delete every demo row that isn't protected, then place the
# seed again through the real agent path. Claude and PayPal are faked, everything else is the real
# app: auth, the mandate and order routes, the intent check's hard rules, auto-capture, the
# rubber-stamp watch and /stats. Whether real Claude holds the same orders only a live run can say.

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from keyed_client import AGENT_HEADERS, MERCHANT_HEADERS, MERCHANT_KEY
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import demo, demo_seed, mandates, orders, review, rubber_stamp, stats
from backend.app.auth import issue_session_token
from backend.app.config import get_settings
from backend.app.db import Base, get_session
from backend.app.demo_seed_orders import SEED_ORDERS
from backend.app.models import (
    Approval,
    ApprovalAction,
    Dispute,
    Mandate,
    Order,
    OrderStatus,
    ReviewState,
)
from backend.scripts import seed_demo

DISPUTED_PAYPAL_ORDER = "25136698AG394644B"
SEED_AGENT_KEYS = "ca-test-key:Checkout Anything,er-test-key:Errand Runner"

# the script sets a real timeout on every call, and TestClient grumbles about being given one
pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")


class FakeClaude:
    # both Claude calls come through here: parsing the mandate, and checking the order. it holds
    # the two seed orders that are really wrong (a Medium blanket, a whole loaf) and passes the
    # rest. the tote at the wrong store is the store rule's to catch, not Claude's

    def __init__(self):
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def with_options(self, **options):
        return self

    def _create(self, **kwargs):
        name = kwargs["tools"][0]["name"]
        content = kwargs["messages"][0]["content"]
        if name == "record_mandate":
            fields = self.parse_mandate(content)
        else:
            fields = self.check_order(content)
        block = SimpleNamespace(type="tool_use", name=name, input=fields)
        return SimpleNamespace(stop_reason="tool_use", content=[block])

    def parse_mandate(self, content):
        return {
            "item": "something", "category": None, "color": None, "size": None,
            "quantity": None, "max_price": 500, "currency": "USD",
            "max_price_inclusive": True, "merchant": None, "expires_at": None, "notes": None,
        }

    def check_order(self, content):
        order_text = content.split("<order>")[1]
        wrong_size = "Medium" in order_text
        whole_loaf = "Sourdough Loaf" in order_text and "Half loaf" not in order_text
        if wrong_size or whole_loaf:
            return {"verdict": "mismatch", "risk_score": 80, "reason": "Wrong size.",
                    "mismatched_fields": ["size"]}
        return {"verdict": "match", "risk_score": 5, "reason": "Matches.",
                "mismatched_fields": []}


class FakePayPal:
    def __init__(self):
        self.created = 0
        self.captured = []
        self.voided = []
        self.void_fails = False

    def create_order(self, body, request_id=None):
        self.created += 1
        return {"id": "PP" + uuid.uuid4().hex[:10], "status": "COMPLETED", "purchase_units": [{
            "payments": {"authorizations": [{
                "id": "AUTH" + uuid.uuid4().hex[:10],
                "status": "CREATED",
                "expiration_time": "2099-01-01T00:00:00Z",
            }]}
        }]}

    def capture_authorization(self, authorization_id, request_id=None, budget_seconds=None):
        self.captured.append(authorization_id)
        return {"id": "CAP" + authorization_id, "status": "COMPLETED"}

    def void_authorization(self, authorization_id, request_id=None):
        if self.void_fails:
            raise requests.ConnectionError("PayPal is down")
        self.voided.append(authorization_id)
        return {"id": authorization_id, "status": "VOIDED"}


@pytest.fixture(autouse=True)
def seed_agents(monkeypatch):
    # the two agents the seed orders as, both allowed to name the store, and a wallet to pay with
    monkeypatch.setenv("AGENT_API_KEYS", SEED_AGENT_KEYS)
    monkeypatch.setenv("STORE_NAMING_AGENTS", "Checkout Anything,Errand Runner")
    monkeypatch.setenv("DEMO_VAULT_ID", "test-vault")
    monkeypatch.setenv("DEMO_PROTECTED_PAYPAL_ORDER_IDS", DISPUTED_PAYPAL_ORDER)
    get_settings.cache_clear()
    # SQLite has one connection here, so the seed can't run orders side by side
    monkeypatch.setattr(demo_seed, "SEED_WORKERS", 1)
    # a fresh job per test, the module one would remember the last test's reset
    monkeypatch.setattr(demo, "reset_job", demo.ResetJob())


@pytest.fixture
def sessions():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    # Postgres refuses to delete an order a dispute still points at. SQLite only does if asked
    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def paypal():
    return FakePayPal()


@pytest.fixture
def client(sessions, paypal):
    claude = FakeClaude()
    app = FastAPI()
    app.include_router(mandates.router)
    app.include_router(orders.router)
    app.include_router(review.router)
    app.include_router(demo.router)
    app.include_router(stats.router)

    def test_session():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[mandates.get_anthropic_client] = lambda: claude
    app.dependency_overrides[orders.get_anthropic_client] = lambda: claude
    app.dependency_overrides[orders.get_paypal_client] = lambda: paypal
    return TestClient(app)


def ago(**delta):
    return datetime.now(timezone.utc) - timedelta(**delta)


def later(days=1):
    return datetime.now(timezone.utc) + timedelta(days=days)


def add_order(session, mandate, status, review_state=None, agent_name=None, paypal_order_id=None,
              expires_at=None, capture_id=None):
    order = Order(
        mandate_id=mandate.id, items=[], total=10, currency="USD", status=status,
        review_state=review_state, agent_name=agent_name, paypal_order_id=paypal_order_id,
        capture_id=capture_id, authorization_id="AUTH-OLD-" + uuid.uuid4().hex[:6],
        authorization_expires_at=expires_at,
    )
    session.add(order)
    session.flush()
    return order


@pytest.fixture
def messy(sessions):
    # what the live database looks like before the first reset: old week1-e2e runs with no agent,
    # the one with the sandbox dispute on it, manual testing, a /place-order order, an open hold
    # nobody opened, and one somebody opened hours ago and walked away from
    ids = {}
    with sessions() as session:
        e2e = Mandate(buyer_label="week1-e2e", raw_request="x", rules={})
        shopper = Mandate(buyer_label="Checkout Anything shopper", raw_request="y", rules={})
        session.add_all([e2e, shopper])
        session.flush()

        disputed = add_order(session, e2e, OrderStatus.captured, ReviewState.auto_approved,
                             paypal_order_id=DISPUTED_PAYPAL_ORDER, capture_id="6MK69796MX034435J")
        ids["disputed"] = disputed.id
        session.add(Dispute(paypal_dispute_id="PP-D-TEST-1", order_id=disputed.id,
                            reason="MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
                            status="WAITING_FOR_SELLER_RESPONSE"))
        # a page on it left open long ago: "Opened, deciding" with nobody deciding
        session.add(Approval(order_id=disputed.id, opened_at=ago(hours=3)))

        ids["old_e2e"] = add_order(session, e2e, OrderStatus.voided, ReviewState.rejected).id
        ids["demo_page"] = add_order(session, shopper, OrderStatus.captured, ReviewState.approved,
                                     agent_name="Demo page").id
        # three fast human approvals: the watch would be in sharp mode if they survived
        for minutes in (30, 20, 10):
            fast = add_order(session, shopper, OrderStatus.captured, ReviewState.approved,
                             agent_name="Checkout Anything")
            session.add(Approval(order_id=fast.id, action=ApprovalAction.approve,
                                 opened_at=ago(minutes=minutes), decided_at=ago(minutes=minutes),
                                 decision_ms=500))
        ids["open_hold"] = add_order(session, shopper, OrderStatus.authorized,
                                     ReviewState.needs_review, agent_name="Checkout Anything",
                                     expires_at=later()).id
        stale = add_order(session, shopper, OrderStatus.authorized, ReviewState.needs_review,
                          agent_name="Checkout Anything", expires_at=later())
        ids["stale_open"] = stale.id
        session.add(Approval(order_id=stale.id, opened_at=ago(minutes=50)))
        session.commit()
    return ids


def reset(client, headers=MERCHANT_HEADERS):
    # POST, then wait for the background thread, then the final status
    response = client.post("/demo/reset", headers=headers)
    if response.status_code == 202:
        demo.reset_job.thread.join(timeout=30)
        assert not demo.reset_job.thread.is_alive()
        return response, client.get("/demo/reset", headers=MERCHANT_HEADERS).json()
    return response, None


def all_orders(client):
    return client.get("/orders?limit=200", headers=MERCHANT_HEADERS).json()


# ---- the state a reset leaves ----


def test_reset_voids_wipes_and_reseeds_to_the_target_state(client, messy, paypal, sessions):
    response, status = reset(client)
    assert response.status_code == 202
    assert status["state"] == "done", status
    for order in status["orders"]:
        assert order["problem"] is None, order

    # both open holds were voided at PayPal before anything was deleted
    assert sorted(status["voided_order_ids"]) == sorted([messy["open_hold"], messy["stale_open"]])
    assert status["protected_order_ids"] == [messy["disputed"]]

    counts = seed_demo.count_orders(all_orders(client))
    # the 10 seed orders plus the one the dispute is on
    assert counts["orders"] == len(SEED_ORDERS) + 1 == 11
    assert counts["auto_captured"] == 7 + 1
    assert counts["approved"] == 2
    assert counts["rejected"] == 1
    assert counts["voided"] == 1
    assert counts["held"] == 3
    assert counts["pending"] == 0
    assert counts["by_agent"]["Checkout Anything"]["orders"] == 5
    assert counts["by_agent"]["Errand Runner"]["orders"] == 5
    # the dispute's order has no agent name, it's from before orders had one
    assert counts["by_agent"]["Unknown agent"]["orders"] == 1
    assert "Demo page" not in counts["by_agent"]


def test_the_dispute_and_its_order_survive(client, messy, sessions):
    reset(client)
    with sessions() as session:
        order = session.get(Order, messy["disputed"])
        assert order is not None
        assert order.paypal_order_id == DISPUTED_PAYPAL_ORDER
        assert order.status == OrderStatus.captured
        assert order.mandate.buyer_label == "week1-e2e"
        assert session.scalars(select(Dispute)).one().order_id == messy["disputed"]
        # the page left open on it no longer reads "Opened, deciding"
        assert session.scalars(select(Approval).where(Approval.order_id == order.id)).all() == []
        # the other old e2e order went, the shared mandate stayed for the one that's kept.
        # by content, not id: SQLite hands a deleted id to the next new row
        e2e_orders = session.scalars(select(Order).where(Order.mandate_id == order.mandate_id))
        assert len(e2e_orders.all()) == 1
        assert session.scalars(select(Order).where(Order.agent_name == "Demo page")).all() == []


def test_rubber_stamp_watch_starts_at_zero_with_sharp_mode_off(client, messy):
    _, status = reset(client)
    assert status["state"] == "done"
    watch = client.get("/stats", headers=MERCHANT_HEADERS).json()
    assert watch["fast_streak"] == 0
    assert watch["rubber_stamp_active"] is False
    # the seed's own decisions aren't in the list the watch reads
    assert watch["recent_decision_ms"] == []
    assert watch["median_decision_ms"] is None


def test_seed_decisions_say_demo_seed_and_have_no_made_up_times(client, messy, sessions):
    reset(client)
    with sessions() as session:
        approvals = session.scalars(select(Approval)).all()
        assert len(approvals) == 3
        actions = []
        for approval in approvals:
            assert approval.decided_by == "demo seed"
            assert approval.opened_at is None
            assert approval.decision_ms is None
            assert approval.decided_at is not None
            actions.append(approval.action)
        assert sorted(action.value for action in actions) == ["approve", "approve", "reject"]


def test_quill_and_pipkin_is_nowhere_in_the_seed(client, messy):
    _, status = reset(client)
    for order in all_orders(client):
        assert "Quill" not in (order["merchant"] or "")
        assert "Quill" not in order["mandate"]["raw_request"]
    stores = set()
    for order in status["orders"]:
        stores.add(order["store"])
    assert stores == {"Fernwood & Thistle Goods", "Hollowbrook Bakery"}


def test_every_seed_order_is_real_and_tagged(client, messy, paypal):
    reset(client)
    seeded = []
    for order in all_orders(client):
        if order["mandate"]["buyer_label"].startswith(demo_seed.SEED_LABEL_PREFIX):
            seeded.append(order)
    assert len(seeded) == len(SEED_ORDERS)
    for order in seeded:
        # every one was a PayPal order with a hold, and it was checked
        assert order["paypal_order_id"].startswith("PP")
        assert order["authorization_id"]
        assert order["intent_check"] is not None
    # 10 holds placed, 9 captured (7 clean, 2 approved). the tote and the 2 old holds voided
    assert paypal.created == len(SEED_ORDERS)
    assert len(paypal.captured) == 9
    assert len(paypal.voided) == 3


def test_reset_twice_gives_the_same_state(client, messy):
    first_response, first = reset(client)
    second_response, second = reset(client)
    assert first_response.status_code == second_response.status_code == 202
    assert second["state"] == "done"
    # the second one had nothing open to void, and found the first one's seed to delete
    assert second["voided_holds"] == 0
    assert second["deleted_orders"] == len(SEED_ORDERS)
    assert second["protected_order_ids"] == first["protected_order_ids"]

    def shape(status):
        rows = []
        for order in status["orders"]:
            rows.append((order["name"], order["agent_name"], order["store"], order["status"],
                         order["review_state"]))
        return sorted(rows)

    assert shape(first) == shape(second)
    counts = seed_demo.count_orders(all_orders(client))
    assert counts["orders"] == 11
    assert counts["pending"] == 0


# ---- what stops a reset ----


def test_refused_while_a_human_has_a_review_open(client, messy, sessions, paypal):
    with sessions() as session:
        session.add(Approval(order_id=messy["open_hold"], opened_at=ago(minutes=2)))
        session.commit()

    response, _ = reset(client)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["order_ids"] == [messy["open_hold"]]
    assert "opened the review" in detail["message"]
    # nothing voided, nothing deleted, no job started
    assert paypal.voided == []
    assert demo.reset_job.snapshot().state == "idle"
    with sessions() as session:
        assert session.get(Order, messy["demo_page"]) is not None


def test_refused_while_a_payment_is_going_through(client, messy, sessions, paypal):
    with sessions() as session:
        session.get(Order, messy["open_hold"]).payment_claimed_at = ago(seconds=5)
        session.commit()
    response, _ = reset(client)
    assert response.status_code == 409
    assert paypal.voided == []


def test_refused_up_front_without_an_errand_runner_key(client, messy, monkeypatch, paypal):
    monkeypatch.setenv("AGENT_API_KEYS", "ca-test-key:Checkout Anything")
    get_settings.cache_clear()
    response, _ = reset(client)
    assert response.status_code == 503
    assert "AGENT_API_KEYS has no key named Errand Runner" in response.json()["detail"]["message"]
    assert paypal.voided == []


def test_refused_up_front_when_errand_runner_cant_name_the_store(client, monkeypatch):
    monkeypatch.setenv("STORE_NAMING_AGENTS", "Checkout Anything")
    get_settings.cache_clear()
    response, _ = reset(client)
    assert response.status_code == 503
    assert "STORE_NAMING_AGENTS" in response.json()["detail"]["message"]


def test_a_failed_void_stops_it_before_anything_is_deleted(client, messy, sessions, paypal):
    paypal.void_fails = True
    response, status = reset(client)
    assert response.status_code == 202
    assert status["state"] == "failed"
    assert "couldn't void" in status["error"]
    with sessions() as session:
        assert session.get(Order, messy["open_hold"]).status == OrderStatus.authorized
        assert session.get(Order, messy["demo_page"]) is not None
    assert paypal.created == 0


def test_only_one_reset_at_a_time(client):
    demo.reset_job.update(state="running")
    response = client.post("/demo/reset", headers=MERCHANT_HEADERS)
    assert response.status_code == 409


def test_rate_limited(client):
    for _ in range(demo.RESET_MAX_TRIES):
        response, status = reset(client)
        assert response.status_code == 202
        assert status["state"] == "done"
    response, _ = reset(client)
    assert response.status_code == 429


def test_needs_the_merchant(client):
    assert client.post("/demo/reset", headers=AGENT_HEADERS).status_code == 401
    assert client.post("/demo/reset").status_code == 401
    assert client.get("/demo/reset", headers=AGENT_HEADERS).status_code == 401


def test_the_dashboard_session_can_reset(client):
    token, _ = issue_session_token()
    response, status = reset(client, {"Authorization": "Bearer " + token})
    assert response.status_code == 202
    assert status["state"] == "done"


# ---- the watch leaves the seed's decisions out ----


def test_seed_decisions_never_count_toward_the_streak(sessions):
    with sessions() as session:
        mandate = Mandate(buyer_label="x", raw_request="x", rules={})
        session.add(mandate)
        session.flush()
        # three human fast approvals, then three newer seed ones. the seed's would end the streak
        # if they counted, since they have no time
        for index in range(3):
            order = add_order(session, mandate, OrderStatus.captured, ReviewState.approved)
            session.add(Approval(order_id=order.id, action=ApprovalAction.approve,
                                 opened_at=ago(minutes=10 - index),
                                 decided_at=ago(minutes=10 - index), decision_ms=400))
        for index in range(3):
            order = add_order(session, mandate, OrderStatus.captured, ReviewState.approved)
            session.add(Approval(order_id=order.id, action=ApprovalAction.approve,
                                 decided_by=rubber_stamp.SEED_DECIDER,
                                 decided_at=ago(minutes=1 - index / 10)))
        session.commit()

        recent = rubber_stamp.load_recent_decisions(session)
        assert len(recent) == 3
        for approval in recent:
            assert approval.decided_by is None
        assert rubber_stamp.get_fast_streak(recent) == 3


# ---- the script ----


def test_script_resets_and_counts(client, messy, capsys):
    api = seed_demo.CheckApi(client, "", MERCHANT_KEY)

    def wait_for_thread(seconds):
        demo.reset_job.thread.join(timeout=30)

    status = seed_demo.run_reset(api, sleep=wait_for_thread)
    assert status["state"] == "done"
    seed_demo.print_seed_orders(status)
    counts = seed_demo.count_orders(api.call("GET", "/orders?limit=200"))
    seed_demo.print_counts(counts, api.call("GET", "/stats"))
    printed = capsys.readouterr().out
    assert "sneaky: tote at the wrong store" in printed
    assert "WRONG" not in printed
    assert "Orders 11: captured 10 (auto 8, approved 2), held 3, voided 1" in printed
    assert "Errand Runner: 5 orders, 4 captured, 2 held, 1 voided" in printed
    assert "Rubber-stamp watch: 0 of 3, sharp mode off" in printed
