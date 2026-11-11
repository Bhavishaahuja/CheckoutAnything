# Places the demo seed (demo_seed_orders.py) after Reset demo has wiped the old orders. demo.py
# runs it, from POST /demo/reset.
#
# Nothing here writes an order row by hand. Each order is placed the way a shopping agent places
# one: its key from AGENT_API_KEYS is turned into its name by the same function the X-API-Key
# check uses, then the POST /mandates and POST /orders route functions run with it. That's a real
# hold in the PayPal sandbox, the real intent check, and the real auto-capture.
#
# The orders Check holds get decided here too, since nobody is around to tap. Same money moves as
# the review link (claim, then capture or void with the derived PayPal-Request-Id), but the approval
# row says decided_by "demo seed" and has no opened_at and no decision_ms: nobody looked, so there
# is no time to record, and rubber_stamp.py leaves these rows out of the streak.

import logging
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from backend.app import mandates, orders
from backend.app.auth import agent_name_for_key
from backend.app.config import agent_keys, get_settings, store_naming_agents
from backend.app.demo_seed_orders import AUTO_APPROVED, NEEDS_REVIEW, SEED_AGENTS, SEED_ORDERS
from backend.app.demo_seed_orders import SHIPPING as SEED_SHIPPING
from backend.app.models import Approval, ApprovalAction, OrderStatus, ReviewState
from backend.app.rubber_stamp import SEED_DECIDER

logger = logging.getLogger(__name__)

# the part after the colon names the order, so the dashboard can show what each one was for
SEED_LABEL_PREFIX = "seed-demo:"

# orders placed side by side. each one is a couple of Claude calls and a few PayPal calls, so one
# at a time takes a few minutes. tests set this to 1, SQLite can't share its one connection
SEED_WORKERS = 4


class SeedError(Exception):
    pass


def seed_keys_by_name(settings):
    # agent name -> its key, for the agents the seed orders as. the first key wins if one name
    # has two
    keys = {}
    for key, name in agent_keys(settings).items():
        if name in SEED_AGENTS and name not in keys:
            keys[name] = key
    return keys


def setup_problems(settings):
    # what has to be set on the API before the seed can run, in words for the person setting it.
    # checked before the reset deletes anything, so a missing key never leaves an empty demo
    problems = []
    keys = seed_keys_by_name(settings)
    for name in SEED_AGENTS:
        if name not in keys:
            problems.append(
                "AGENT_API_KEYS has no key named " + name + ". Add one, like "
                "<new random key>:" + name
            )
    naming = store_naming_agents(settings)
    for name in SEED_AGENTS:
        if name not in naming:
            problems.append(
                "STORE_NAMING_AGENTS doesn't list " + name + ", so its orders can't say which "
                "store they're at"
            )
    if not settings.demo_vault_id:
        problems.append("DEMO_VAULT_ID isn't set, so there's no saved wallet to pay with")
    return problems


def order_items(scenario):
    items = []
    for item in scenario["items"]:
        items.append(orders.OrderItemIn(**item))
    return items


def place_seed_order(session_factory, paypal, claude, scenario, key, vault_id):
    # as the agent with this key: the mandate in the human's words, then the order. returns the
    # order id. a PayPal failure comes out as the route's own HTTPException
    agent_name = agent_name_for_key(key, agent_keys(get_settings()))
    session = session_factory()
    try:
        mandate = mandates.create_mandate(
            mandates.MandateCreate(
                buyer_label=SEED_LABEL_PREFIX + scenario["name"],
                request_text=scenario["request"],
                merchant=scenario["store"],
            ),
            session,
            claude,
        )
        placed = orders.create_order(
            orders.OrderCreate(
                mandate_id=mandate.id,
                items=order_items(scenario),
                shipping=Decimal(scenario.get("shipping", SEED_SHIPPING)),
                vault_id=vault_id,
                merchant=scenario.get("order_at", scenario["store"]),
            ),
            session,
            paypal,
            claude,
            agent_name,
        )
        return placed.id
    finally:
        session.close()


def decide_as_seed(session, paypal, order_id, action):
    # approve captures, reject voids. same claim and same request ids as a tap on the review link,
    # so this can't move money twice or race a human. raises SeedError if it couldn't
    order, blocker = orders.claim_order(session, order_id)
    if blocker is not None:
        session.rollback()
        raise SeedError(blocker)

    try:
        if action == ApprovalAction.approve:
            result = orders.capture_payment(paypal, order)
        else:
            result = paypal.void_authorization(
                order.authorization_id,
                request_id=orders.payment_request_id(order, orders.VOID),
            )
    except orders.PAYPAL_FAILURES as error:
        orders.release_claim(session, order_id)
        raise SeedError("PayPal couldn't " + action.value + " order " + str(order_id)) from error

    order = orders.load_order(session, order_id, lock=True)
    order.payment_claimed_at = None
    if action == ApprovalAction.approve:
        order.capture_id = result.get("id")
        if result.get("status") == "DECLINED":
            order.status = OrderStatus.failed
        else:
            order.status = OrderStatus.captured
            order.review_state = ReviewState.approved
    else:
        order.status = OrderStatus.voided
        order.review_state = ReviewState.rejected
        # a 204 with no body is also a documented success
        order.void_result = result.get("status") if result else "VOIDED"
    # no opened_at and no decision_ms: nobody looked at it, so there's no time to record
    session.add(Approval(
        order_id=order_id,
        action=action,
        decided_by=SEED_DECIDER,
        decided_at=orders.utc_now(),
    ))
    session.commit()


def run_scenario(session_factory, paypal, claude, scenario, keys, vault_id):
    # place one seed order and settle it. returns what happened, with a problem when it didn't land
    # where it was meant to. never raises, so one bad order doesn't stop the rest
    result = {
        "name": scenario["name"],
        "agent_name": scenario["agent"],
        "store": scenario.get("order_at", scenario["store"]),
        "expected": scenario["expected"],
        "order_id": None,
        "status": None,
        "review_state": None,
        "problem": None,
    }
    try:
        order_id = place_seed_order(
            session_factory, paypal, claude, scenario, keys[scenario["agent"]], vault_id
        )
        result["order_id"] = order_id

        session = session_factory()
        try:
            order = orders.load_order(session, order_id)
            landed = order.review_state
            if order.status == OrderStatus.authorized and landed == ReviewState.needs_review:
                # nothing may be left on hold, the live holds come from the person on camera.
                # a clean one Check held anyway gets approved, and the problem says so
                action = ApprovalAction(scenario.get("decide") or "approve")
                decide_as_seed(session, paypal, order_id, action)
                if scenario["expected"] != NEEDS_REVIEW:
                    result["problem"] = "Check held it, expected it to capture on its own"
            elif scenario["expected"] == NEEDS_REVIEW:
                result["problem"] = "expected a hold, Check left it " + str(order.status.value)

            order = orders.load_order(session, order_id)
            session.refresh(order)
            result["status"] = order.status.value
            result["review_state"] = order.review_state.value if order.review_state else None
            if order.status == OrderStatus.failed and result["problem"] is None:
                result["problem"] = "PayPal failed the order"
            if scenario["expected"] == AUTO_APPROVED and result["review_state"] is None:
                result["problem"] = result["problem"] or "never got a hold"
        finally:
            session.close()
    except HTTPException as error:
        result["problem"] = describe_http_error(error)
    except (SeedError, SQLAlchemyError) as error:
        result["problem"] = str(error)
    except Exception as error:  # noqa: BLE001
        # anything else from Claude or PayPal. logged in full, the dashboard gets the short form
        logger.exception("Seed order %s failed", scenario["name"])
        result["problem"] = type(error).__name__ + ": " + str(error)[:200]
    return result


def describe_http_error(error):
    detail = error.detail
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)
    return str(detail)


def place_seed_orders(session_factory, paypal, claude, on_done=None, scenarios=None):
    # every seed order, a few at a time. on_done(result) is called as each one finishes, which is
    # how the reset's progress counts up. returns the results in the list's own order
    if scenarios is None:
        scenarios = SEED_ORDERS
    settings = get_settings()
    problems = setup_problems(settings)
    if problems:
        raise SeedError(problems[0])
    keys = seed_keys_by_name(settings)
    vault_id = settings.demo_vault_id

    def run(scenario):
        result = run_scenario(session_factory, paypal, claude, scenario, keys, vault_id)
        if on_done is not None:
            on_done(result)
        return result

    results = []
    if SEED_WORKERS <= 1:
        for scenario in scenarios:
            results.append(run(scenario))
        return results

    with ThreadPoolExecutor(max_workers=SEED_WORKERS) as pool:
        futures = []
        for scenario in scenarios:
            futures.append(pool.submit(run, scenario))
        for future in futures:
            results.append(future.result())
    return results
