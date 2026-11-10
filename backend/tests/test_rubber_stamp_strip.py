# The strip above the orders grid: Check's rubber-stamp watch and how often each agent's
# orders get held. Check is faked, same as test_check.py.

from fastapi.testclient import TestClient

from backend.app.models import Order
from backend.app.orders import held_rates
from backend.tests.fakes import FakeCheck
from backend.tests.test_check import MISMATCH, agent_buys, connect_store, fresh


def make_order(created_by="agent", review_state=None, verdict=None, check_id=1,
               replaces=None):
    return Order(created_by=created_by, review_state=review_state, check_verdict=verdict,
                 check_order_id=check_id, check_replaces_id=replaces)


# ---- GET /check/stats ----


def test_check_stats_returns_only_the_watch_fields():
    world = fresh(FakeCheck())
    with TestClient(world.app) as client:
        response = client.get("/check/stats")
        assert response.status_code == 200
        assert response.json() == {
            "rubber_stamp_active": True,
            "fast_streak": 3,
            "fast_threshold_ms": 2000,
            "median_decision_ms": 1400,
        }


def test_check_stats_says_when_the_watch_is_off():
    check = FakeCheck()
    check.stats["rubber_stamp_active"] = False
    check.stats["fast_streak"] = 0
    check.stats["median_decision_ms"] = None
    world = fresh(check)
    with TestClient(world.app) as client:
        stats = client.get("/check/stats").json()
        assert stats["rubber_stamp_active"] is False
        assert stats["fast_streak"] == 0
        assert stats["median_decision_ms"] is None


def test_check_stats_is_503_without_check():
    world = fresh(None)
    with TestClient(world.app) as client:
        response = client.get("/check/stats")
        assert response.status_code == 503
        assert response.json()["detail"] == "CHECK_URL isn't set on the API"


def test_check_stats_is_503_without_the_merchant_key():
    world = fresh(FakeCheck(can_read=False))
    with TestClient(world.app) as client:
        response = client.get("/check/stats")
        assert response.status_code == 503
        assert response.json()["detail"] == "CHECK_MERCHANT_KEY isn't set on the API"


# ---- the held-rate math ----


def test_held_rate_with_no_orders():
    assert held_rates([]) == []


def test_held_rate_when_everything_was_held():
    orders = [
        make_order(review_state="needs_review"),
        make_order(review_state="approved"),
        make_order(review_state="rejected"),
    ]
    assert held_rates(orders) == [
        {"created_by": "agent", "total": 3, "held": 3, "held_pct": 100},
    ]


def test_held_rate_mixed_and_per_agent():
    orders = [
        make_order(review_state="auto_approved", verdict="match"),
        make_order(review_state="needs_review", verdict="mismatch"),
        make_order(review_state="auto_approved"),
        make_order(review_state="approved"),
        make_order(review_state="auto_approved"),
        # never got a review_state back, the verdict says it would have been held
        make_order(created_by="manual", verdict="mismatch"),
        make_order(created_by="manual", verdict="match"),
        # didn't go through Check, so it doesn't count
        make_order(review_state=None, check_id=None),
        # a fix's replacement isn't a new purchase
        make_order(review_state="auto_approved", replaces=5),
    ]
    assert held_rates(orders) == [
        {"created_by": "agent", "total": 5, "held": 2, "held_pct": 40},
        {"created_by": "manual", "total": 2, "held": 1, "held_pct": 50},
    ]


# ---- GET /orders/agent-stats ----


def test_agent_stats_from_real_orders():
    check = FakeCheck()
    world = fresh(check)
    with TestClient(world.app) as client:
        assert client.get("/orders/agent-stats").json() == {"agents": []}

        store_id, _store = connect_store(client)
        agent_buys(world, client, store_id)
        check.decide = ("authorized", "needs_review", MISMATCH)
        agent_buys(world, client, store_id)

        agents = client.get("/orders/agent-stats").json()["agents"]
        assert agents == [{
            "created_by": "agent", "label": "Checkout Anything shopper",
            "total": 2, "held": 1, "held_pct": 50,
        }]
