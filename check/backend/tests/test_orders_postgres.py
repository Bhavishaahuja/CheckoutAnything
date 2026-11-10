# Taps at the same moment against real Postgres, because the row lock does nothing on SQLite.
# Skipped unless LEASH_TEST_POSTGRES_URL is set, so CI and normal runs never need a database.
# It runs migrations and adds rows, so only ever point it at a throwaway one, in cmd:
#
#   docker run -d --rm --name leash-pg-test -e POSTGRES_PASSWORD=throwaway -e POSTGRES_DB=leash ^
#     -p 127.0.0.1:55432:5432 postgres:16
#   set LEASH_TEST_POSTGRES_URL=postgresql+psycopg://postgres:throwaway@127.0.0.1:55432/leash
#   .venv\Scripts\python.exe -m pytest backend\tests\test_orders_postgres.py -v
#   docker stop leash-pg-test

import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from keyed_client import KeyedClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.app import orders, review
from backend.app.db import get_session
from backend.app.models import Approval, Mandate, Order, OrderStatus, ReviewState

POSTGRES_URL = os.environ.get("LEASH_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="LEASH_TEST_POSTGRES_URL isn't set")

# enough simultaneous taps that they really do pile up on the lock
TAPS = 8
# long enough that every tap arrives while the first one is still waiting on PayPal
PAYPAL_SECONDS = 1.0


class SlowPayPal:
    # counts calls and watches the database while PayPal is "working"

    def __init__(self, engine):
        self.engine = engine
        self.captures = []
        self.voids = []
        self.open_transactions = []
        self.lock = threading.Lock()

    def _during_the_call(self):
        # ours is the one connection allowed to be here, everything else should be idle
        with self.engine.connect() as connection:
            count = connection.execute(text(
                "SELECT count(*) FROM pg_stat_activity WHERE state LIKE 'idle in transaction%' "
                "AND pid <> pg_backend_pid()"
            )).scalar()
        self.open_transactions.append(count)
        time.sleep(PAYPAL_SECONDS)

    def capture_authorization(self, authorization_id, request_id=None, budget_seconds=None):
        with self.lock:
            self.captures.append(request_id)
        self._during_the_call()
        return {"id": "CAPTURE-" + uuid.uuid4().hex[:8], "status": "COMPLETED"}

    def void_authorization(self, authorization_id, request_id=None):
        with self.lock:
            self.voids.append(request_id)
        self._during_the_call()
        return {"id": authorization_id, "status": "VOIDED"}


@pytest.fixture(scope="module")
def engine():
    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    command.upgrade(alembic_config, "head")
    # a pool bigger than the taps, so it's the lock they wait on and not a connection
    return create_engine(POSTGRES_URL, pool_size=TAPS + 4)


@pytest.fixture
def sessions(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def paypal(engine):
    return SlowPayPal(engine)


@pytest.fixture
def app(sessions, paypal):
    application = FastAPI()
    application.include_router(orders.router)
    application.include_router(review.router)

    def test_session():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    application.dependency_overrides[get_session] = test_session
    application.dependency_overrides[orders.get_paypal_client] = lambda: paypal
    return application


@pytest.fixture
def order_id(sessions):
    # an order waiting for a human, with a hold in place
    with sessions() as session:
        mandate = Mandate(buyer_label="Sam", raw_request="Trail runners", rules={})
        order = Order(
            mandate=mandate,
            authorization_id="AUTH-" + uuid.uuid4().hex[:8],
            items=[{"name": "Trail runner", "quantity": 1, "unit_price": "98.00"}],
            total=Decimal("98.00"),
            currency="USD",
            status=OrderStatus.authorized,
            review_state=ReviewState.needs_review,
            authorization_expires_at=datetime.now(timezone.utc) + timedelta(days=29),
        )
        session.add(order)
        session.commit()
        return order.id


@pytest.fixture
def wide_race_window(monkeypatch):
    # the gap between reading the order and committing the claim is tiny, so without this one tap
    # usually finishes before the next one reads, and the test passes with the lock removed. this
    # pauses whoever got through the check, inside that gap. with the lock, everyone else waits on
    # the row and then sees the claim. without it, they all get through and PayPal gets charged
    # more than once, every time
    real_blocker = orders.review_blocker

    def slow_blocker(order):
        blocker = real_blocker(order)
        if blocker is None:
            time.sleep(0.3)
        return blocker

    monkeypatch.setattr(orders, "review_blocker", slow_blocker)


@pytest.fixture
def token(app, order_id):
    response = KeyedClient(app).post("/orders/" + str(order_id) + "/review-link")
    assert response.status_code == 201
    return response.json()["review_token"]


def tap_all_at_once(app, paths):
    # every thread waits at the barrier, then they all fire together
    barrier = threading.Barrier(len(paths))
    results = [None] * len(paths)

    def tap(index, path):
        client = TestClient(app)
        barrier.wait()
        results[index] = client.post(path, json={"decision_ms": 1500})

    threads = []
    for index, path in enumerate(paths):
        threads.append(threading.Thread(target=tap, args=(index, path)))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


def status_codes(results):
    codes = []
    for result in results:
        codes.append(result.status_code)
    return sorted(codes)


def test_double_approve_captures_once(app, paypal, sessions, order_id, token, wide_race_window):
    path = "/review/" + token + "/approve"

    results = tap_all_at_once(app, [path] * TAPS)

    assert status_codes(results) == [200] + [409] * (TAPS - 1)
    # the whole point: PayPal was asked exactly once
    assert len(paypal.captures) == 1
    with sessions() as session:
        order = session.get(Order, order_id)
        assert order.status == OrderStatus.captured
        assert order.review_state == ReviewState.approved
        assert order.capture_id is not None
        assert order.payment_claimed_at is None
        assert len(order.approvals) == 1


def test_losing_taps_get_the_current_states_right_away(app, token, wide_race_window):
    # they get a 409 while the first tap is still at PayPal. waiting in line behind it would mean
    # each one holding a connection for the whole PayPal call
    path = "/review/" + token + "/approve"

    started = time.monotonic()
    results = tap_all_at_once(app, [path] * TAPS)
    elapsed = time.monotonic() - started

    conflicts = []
    for result in results:
        if result.status_code == 409:
            conflicts.append(result.json()["detail"])
    assert len(conflicts) == TAPS - 1
    for detail in conflicts:
        assert set(detail) == {"message", "status", "review_state"}
    # nothing queued up behind PayPal, one slow call is all that happened
    assert elapsed < PAYPAL_SECONDS * 2


def test_approve_and_reject_at_the_same_moment_only_one_wins(app, paypal, sessions, order_id,
                                                             token, wide_race_window):
    url = "/review/" + token

    results = tap_all_at_once(app, [url + "/approve", url + "/reject"])

    assert status_codes(results) == [200, 409]
    # money moved one way only
    assert len(paypal.captures) + len(paypal.voids) == 1
    with sessions() as session:
        order = session.get(Order, order_id)
        if paypal.captures:
            assert order.status == OrderStatus.captured
            assert order.review_state == ReviewState.approved
        else:
            assert order.status == OrderStatus.voided
            assert order.review_state == ReviewState.rejected


def test_no_transaction_is_open_during_the_paypal_call(app, paypal, token):
    tap_all_at_once(app, ["/review/" + token + "/approve"])

    assert paypal.open_transactions == [0]


def test_opening_at_the_same_moment_stamps_once(app, sessions, order_id, token):
    # two tabs, or a preview fetch racing the real open. the row lock means one row, one timestamp
    barrier = threading.Barrier(TAPS)
    results = [None] * TAPS

    def open_link(index):
        client = TestClient(app)
        barrier.wait()
        results[index] = client.post("/review/" + token + "/opened").status_code

    threads = []
    for index in range(TAPS):
        threads.append(threading.Thread(target=open_link, args=(index,)))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert results == [204] * TAPS
    with sessions() as session:
        assert session.query(Approval).filter_by(order_id=order_id).count() == 1


def test_server_timing_on_real_timestamps(app, sessions, order_id, token):
    client = TestClient(app)
    assert client.post("/review/" + token + "/opened").status_code == 204
    time.sleep(0.5)

    # lying by a lot
    response = client.post("/review/" + token + "/approve", json={"decision_ms": 1500000})

    assert response.status_code == 200
    with sessions() as session:
        approval = session.query(Approval).filter_by(order_id=order_id).one()
        # timestamptz, so Postgres keeps the zone
        assert approval.decided_at.tzinfo is not None
        assert approval.opened_at.tzinfo is not None
        assert 500 <= approval.decision_ms < 1500
        assert approval.client_decision_ms == 1500000
