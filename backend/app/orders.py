# Agent orders: create (PayPal intent AUTHORIZE), authorize, approve, reject, list, read.
# Response shapes are documented for the frontend in docs/api.md, keep the two in step.
#
# Money flow is what the spikes proved in sandbox:
#   spike 1: create -> buyer approves -> authorize -> capture or void
#   spike 2: create with payment_source.paypal.vault_id -> comes back already authorized,
#            no buyer action. falls back to /authorize if it ever doesn't
#
# status is where the money is, and moves one way only:
#   created -> authorized -> captured
#                         -> voided
#   any PayPal failure while creating/authorizing, or a declined capture -> failed
#
# review_state is who decided. It starts at needs_review the moment there's a hold:
#   needs_review -> auto_approved    clean match below the risk limit, captured right away
#                -> approved         a human tapped approve, captured
#                -> rejected         a human tapped reject, voided
#
# Starting at needs_review means anything going wrong (a crash, a failed save, a PayPal error)
# leaves the order waiting for a human with no money moved. Capture only ever happens by
# something actively deciding to. There's deliberately no plain capture or void endpoint, it
# would let an agent settle its own flagged order.

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from typing import Annotated

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from backend.app import mandate_parser
from backend.app.config import STORE_NAME, get_settings
from backend.app.db import get_session
from backend.app.intent.check import build_decision, run_intent_check
from backend.app.intent.rules import as_utc
from backend.app.models import (
    Approval,
    ApprovalAction,
    CheckedBy,
    Mandate,
    Order,
    OrderStatus,
    ReviewState,
    Verdict,
)
from backend.app.paypal_client import PayPalError, client_from_settings, first_authorization

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["orders"])

CENT = Decimal("0.01")
CURRENCY = "USD"

CAPTURE = "capture"
VOID = "void"

# timeouts and dropped connections come through as requests errors, not PayPalError
PAYPAL_FAILURES = (PayPalError, requests.RequestException)

# long enough to outlast a slow PayPal call (30s for the token plus 30s for the call). after this
# a claim counts as abandoned by a crashed request, and retrying is safe because the same
# PayPal-Request-Id gets the original result back
CLAIM_EXPIRES_AFTER = timedelta(seconds=120)

# the most an Integer column holds, about 24 days, so a silly value is a 422 and not a 500
MAX_DECISION_MS = 2147483647


# ---- request / response shapes ----


class OrderItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    color: str | None = Field(default=None, max_length=100)
    size: str | None = Field(default=None, max_length=100)
    quantity: int = Field(ge=1, le=1000)
    unit_price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class OrderCreate(BaseModel):
    mandate_id: int
    items: list[OrderItemIn] = Field(min_length=1, max_length=50)
    shipping: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    # saved PayPal wallet from spike 2's flow. with it, no buyer popup
    vault_id: str | None = Field(default=None, max_length=64)


class RuleResultOut(BaseModel):
    rule: str
    passed: bool
    reason: str


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    verdict: Verdict
    risk_score: int | None
    reason: str
    # these three are null on decisions saved before the check was wired in
    mismatched_fields: list[str] | None
    rule_results: list[RuleResultOut] | None
    latency_ms: int | None
    checked_by: CheckedBy
    created_at: datetime


class MandateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    buyer_label: str
    raw_request: str
    rules: dict
    max_price: Decimal | None
    max_price_inclusive: bool
    merchant: str | None
    expires_at: datetime | None
    created_at: datetime


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: ApprovalAction | None
    decided_by: str | None
    opened_at: datetime | None
    decided_at: datetime | None
    decision_ms: int | None


class OrderOut(BaseModel):
    # every order endpoint returns at least this, see docs/api.md
    model_config = ConfigDict(from_attributes=True)

    id: int
    mandate_id: int
    paypal_order_id: str | None
    authorization_id: str | None
    capture_id: str | None
    void_result: str | None
    vault_id: str | None
    items: list
    total: Decimal
    shipping_amount: Decimal | None
    currency: str
    status: OrderStatus
    # null until there's a hold to decide about
    review_state: ReviewState | None
    authorization_expires_at: datetime | None
    created_at: datetime
    mandate: MandateSummary
    # the newest check result. null until the order is checked, or if saving the result failed
    intent_check: DecisionOut | None
    # the human's decision. null if nobody has made one
    approval: ApprovalOut | None


class OrderCreated(OrderOut):
    # only set when there's no vault id: the buyer has to open this and approve
    payer_action_url: str | None = None


class OrderDetail(OrderOut):
    # the full history, for GET /orders/{id}
    decisions: list[DecisionOut]
    approvals: list[ApprovalOut]


class ReviewDecision(BaseModel):
    # page open to tap, measured on the client
    decision_ms: int = Field(ge=0, le=MAX_DECISION_MS)


# ---- dependencies ----


@lru_cache
def get_paypal_client():
    # one client for the whole app so the OAuth token cache is shared between requests
    return client_from_settings(get_settings())


@lru_cache
def get_anthropic_client():
    # shared for the same reason, and so tests can swap in a fake. with no API key this still
    # builds fine, the failure comes at call time and the check fails closed
    return mandate_parser.make_client(get_settings().anthropic_api_key)


DbSession = Annotated[Session, Depends(get_session)]
PayPal = Annotated[object, Depends(get_paypal_client)]
Claude = Annotated[object, Depends(get_anthropic_client)]


# ---- helpers ----


def money(value):
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def item_display_name(item):
    # "Trail runner, black, size 9". PayPal item names are free text
    parts = [item.name]
    if item.color:
        parts.append(item.color)
    if item.size:
        parts.append("size " + item.size)
    return ", ".join(parts)


def build_paypal_order(order_id, items, shipping, vault_id, settings):
    # Orders v2 create body. With items, amount.breakdown.item_total has to equal the sum of
    # unit_amount * quantity, and amount.value has to equal item_total + shipping
    paypal_items = []
    item_total = Decimal("0")
    for item in items:
        paypal_items.append({
            "name": item_display_name(item),
            "quantity": str(item.quantity),
            "unit_amount": {"currency_code": CURRENCY, "value": money(item.unit_price)},
            "category": "PHYSICAL_GOODS",
        })
        item_total += item.unit_price * item.quantity

    total = item_total + shipping

    purchase_unit = {
        "reference_id": "leash-order-" + str(order_id),
        # our id rides along so PayPal records (and disputes) point back at this row
        "custom_id": str(order_id),
        "description": STORE_NAME + " agent order",
        "amount": {
            "currency_code": CURRENCY,
            "value": money(total),
            "breakdown": {
                "item_total": {"currency_code": CURRENCY, "value": money(item_total)},
                "shipping": {"currency_code": CURRENCY, "value": money(shipping)},
            },
        },
        "items": paypal_items,
    }

    if vault_id:
        # same as spike 2's order 2: merchant starts a later payment on a saved wallet
        payment_source = {
            "paypal": {
                "vault_id": vault_id,
                "stored_credential": {
                    "payment_initiator": "MERCHANT",
                    "usage": "SUBSEQUENT",
                    "usage_pattern": "IMMEDIATE",
                },
            }
        }
    else:
        # same as spike 1: the buyer approves in the browser first
        payment_source = {
            "paypal": {
                "experience_context": {
                    "brand_name": STORE_NAME,
                    "user_action": "PAY_NOW",
                    "shipping_preference": "GET_FROM_FILE",
                    "return_url": settings.paypal_return_url,
                    "cancel_url": settings.paypal_cancel_url,
                }
            }
        }

    body = {
        "intent": "AUTHORIZE",
        "purchase_units": [purchase_unit],
        "payment_source": payment_source,
    }
    return body, total.quantize(CENT)


def payer_action_link(paypal_order):
    # with payment_source set PayPal says "payer-action", older flows say "approve"
    for link in paypal_order.get("links", []):
        if link.get("rel") in ("payer-action", "approve"):
            return link.get("href")
    return None


def parse_paypal_time(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def paypal_error_response(action, error):
    # PayPal said no. Pass on what it said (debug_id is what PayPal support asks for),
    # as a 502 since the failure is upstream of us
    return HTTPException(
        status_code=502,
        detail={
            "message": "PayPal " + action + " failed",
            "paypal_status": error.status_code,
            "paypal_name": error.name,
            "paypal_issue": error.issue,
            "paypal_message": error.message,
            "debug_id": error.debug_id,
        },
    )


def apply_authorization(order, authorization):
    # CREATED means the hold is in place. anything else (DENIED, PENDING...) we can't capture
    order.authorization_id = authorization.get("id")
    order.authorization_expires_at = parse_paypal_time(authorization.get("expiration_time"))
    if authorization.get("status") == "CREATED":
        order.status = OrderStatus.authorized
        # in the same commit as the hold, so there's never a hold nobody is responsible for
        order.review_state = ReviewState.needs_review
    else:
        order.status = OrderStatus.failed


def load_order(session, order_id, lock=False):
    query = select(Order).where(Order.id == order_id)
    if lock:
        # row lock on Postgres so two requests can't both pass the state checks. the lock alone
        # would still hand back the old values of an order this session already loaded, and
        # those old values are what would get checked, so ask for fresh ones
        query = query.with_for_update().execution_options(populate_existing=True)
    order = session.scalars(query).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order " + str(order_id) + " not found")
    return order


def require_status(order, allowed, action):
    if order.status in allowed:
        return
    reasons = {
        OrderStatus.created: "isn't authorized yet",
        OrderStatus.authorized: "is already authorized",
        OrderStatus.captured: "is already captured",
        OrderStatus.voided: "was voided",
        OrderStatus.failed: "failed at PayPal",
    }
    raise HTTPException(
        status_code=409,
        detail="Can't " + action + " order " + str(order.id) + ": it "
        + reasons[order.status] + " (status " + order.status.value + ")",
    )


def utc_now():
    return datetime.now(timezone.utc)


def payment_request_id(order, action):
    # the same order and action always gets the same PayPal-Request-Id, so a retry gets PayPal's
    # original result and can't capture twice. the authorization id is in there because order ids
    # restart in every database, and local and Render share one sandbox account: on its own,
    # order 1 here could get back the capture of a different order 1 over there
    seed = "leash:" + str(order.id) + ":" + str(order.authorization_id) + ":" + action
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def review_blocker(order):
    # why nobody can settle this order right now, or None if they can
    if order.status != OrderStatus.authorized or order.review_state != ReviewState.needs_review:
        return "Order " + str(order.id) + " isn't waiting for review"

    if order.payment_claimed_at is not None:
        if utc_now() - as_utc(order.payment_claimed_at) < CLAIM_EXPIRES_AFTER:
            return "Order " + str(order.id) + " already has a payment in progress"
    return None


def claim_order(session, order_id):
    # lock, check, mark it taken, commit. the commit lets go of the lock before PayPal gets
    # called, so no connection waits on PayPal, and the claim is what stops a second request:
    # it now sees the claim and gets a 409 straight away, instead of queueing on the lock.
    # returns (order, reason it can't be claimed). the lock is still held if there is a reason
    order = load_order(session, order_id, lock=True)
    blocker = review_blocker(order)
    if blocker is None:
        order.payment_claimed_at = utc_now()
        session.commit()
    return order, blocker


def release_claim(session, order_id):
    # PayPal failed, so let someone try again. if this fails too, the claim just expires
    try:
        order = load_order(session, order_id, lock=True)
        order.payment_claimed_at = None
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        logger.exception("Couldn't release the payment claim on order %s", order_id)


def capture_payment(paypal, order):
    capture = paypal.capture_authorization(
        order.authorization_id, request_id=payment_request_id(order, CAPTURE)
    )
    # it's the id that disputes need later, so an answer without one isn't a usable capture
    if not capture or not capture.get("id"):
        raise PayPalError(200, message="Capture response had no id")
    return capture


def finish_capture(session, order_id, capture, review_state, approval=None):
    # returns True if the money was taken. a decline leaves review_state as it was
    order = load_order(session, order_id, lock=True)
    order.capture_id = capture.get("id")
    order.payment_claimed_at = None

    captured = capture.get("status") != "DECLINED"
    if captured:
        # COMPLETED, or PENDING while PayPal finishes. either way the money is taken
        order.status = OrderStatus.captured
        order.review_state = review_state
        if approval is not None:
            session.add(approval)
    else:
        order.status = OrderStatus.failed
    session.commit()
    return captured


def auto_decide(session, order_id, paypal):
    # the order is already needs_review, so this only ever has to do something to move money.
    # returning early is the safe outcome for every odd case, including a null intent_check
    order = load_order(session, order_id)
    check = order.intent_check
    if check is None or check.verdict != Verdict.match or check.risk_score is None:
        return
    if check.risk_score >= get_settings().auto_capture_max_risk:
        return

    order, blocker = claim_order(session, order_id)
    if blocker is not None:
        # a human got here first, in the seconds the check was running
        session.rollback()
        logger.info("Skipping auto-capture: %s", blocker)
        return

    try:
        capture = capture_payment(paypal, order)
    except PAYPAL_FAILURES:
        # no retry in here: the agent is waiting, and a human can approve it now
        logger.exception("Auto-capture failed for order %s, sending to review", order_id)
        release_claim(session, order_id)
        return

    try:
        captured = finish_capture(session, order_id, capture, ReviewState.auto_approved)
    except SQLAlchemyError:
        # stays needs_review with the claim on it. once that expires, approving sends the same
        # PayPal-Request-Id, gets this same capture back, and saves it
        session.rollback()
        logger.exception(
            "Order %s was captured at PayPal as %s but saving that failed",
            order_id, capture.get("id"),
        )
        return

    if not captured:
        logger.error("PayPal declined the auto-capture of order %s", order_id)


def check_and_decide(session, order, paypal, claude):
    order_id = order.id
    check_and_save(session, order, claude)
    # the hold is committed and the agent is about to get an answer. failing here would look like
    # the purchase failed and could make it buy again, and the order is safely in needs_review
    try:
        auto_decide(session, order_id, paypal)
    except SQLAlchemyError:
        session.rollback()
        logger.exception("Auto-decide failed for order %s, sending to review", order_id)


def review_conflict(order, message):
    return HTTPException(
        status_code=409,
        detail={
            "message": message,
            "status": order.status.value,
            "review_state": order.review_state.value if order.review_state else None,
        },
    )


def payment_failed(action):
    # nothing changed: if we got this far the order was authorized and waiting for review. these
    # are known values, not read from the order, because the database may be what just failed.
    # the debug_id is in the log, the phone only needs to know to try again
    return HTTPException(
        status_code=502,
        detail={
            "message": "PayPal " + action + " failed, the order is still waiting for review",
            "status": OrderStatus.authorized.value,
            "review_state": ReviewState.needs_review.value,
        },
    )


def save_failed(action, order_id):
    # PayPal did it but we couldn't record it. retrying is safe, same PayPal-Request-Id
    return HTTPException(
        status_code=502,
        detail={"message": "PayPal " + action + " went through but order "
                + str(order_id) + " couldn't be updated, try again in a couple of minutes"},
    )


def claim_for_review(session, order_id):
    order, blocker = claim_order(session, order_id)
    if blocker is not None:
        # build it before the rollback, which throws away the values it reads
        conflict = review_conflict(order, blocker)
        session.rollback()
        raise conflict
    return order


def build_approval(order_id, action, tapped_at, decision_ms):
    return Approval(
        order_id=order_id,
        action=action,
        opened_at=tapped_at - timedelta(milliseconds=decision_ms),
        decided_at=tapped_at,
        decision_ms=decision_ms,
    )


def check_and_save(session, order, claude):
    # the order was committed as authorized before this runs, so whatever happens in here the
    # hold is on record and it's waiting for review
    mandate = order.mandate

    # Claude can take up to 20 seconds. ending the transaction hands the connection back to the
    # pool instead of sitting on one that long. objects stay usable, expire_on_commit is off
    session.commit()

    result = run_intent_check(mandate, order, client=claude)

    # a failed save can't fail the request: the agent would see an error and may buy again,
    # placing a second hold. the order just comes back with intent_check null
    try:
        session.add(build_decision(order, result))
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        logger.exception("Couldn't save the intent check for order %s", order.id)


# ---- endpoints ----


@router.post("", response_model=OrderCreated, status_code=201)
def create_order(body: OrderCreate, session: DbSession, paypal: PayPal, claude: Claude):
    mandate = session.get(Mandate, body.mandate_id)
    if mandate is None:
        raise HTTPException(
            status_code=404, detail="Mandate " + str(body.mandate_id) + " not found"
        )

    items_json = []
    for item in body.items:
        items_json.append({
            "name": item.name,
            "color": item.color,
            "size": item.size,
            "quantity": item.quantity,
            "unit_price": money(item.unit_price),
        })

    # save first so the PayPal order can carry our id
    order = Order(
        mandate_id=mandate.id,
        items=items_json,
        total=Decimal("0"),
        # quantized so a defaulted "0" still reads back as 0.00
        shipping_amount=body.shipping.quantize(CENT),
        currency=CURRENCY,
        vault_id=body.vault_id,
        status=OrderStatus.created,
    )
    session.add(order)
    session.flush()

    paypal_body, total = build_paypal_order(
        order.id, body.items, body.shipping, body.vault_id, get_settings()
    )
    order.total = total

    try:
        paypal_order = paypal.create_order(paypal_body)
        order.paypal_order_id = paypal_order.get("id")

        payer_action_url = None
        if body.vault_id:
            # spike 2: a vault_id order comes back COMPLETED with the authorization inside.
            # if this sandbox ever returns it un-authorized, authorize it ourselves
            authorization = first_authorization(paypal_order)
            if authorization is None:
                paypal_order = paypal.authorize_order(order.paypal_order_id)
                authorization = first_authorization(paypal_order)
            if authorization is None:
                order.status = OrderStatus.failed
            else:
                apply_authorization(order, authorization)
        else:
            payer_action_url = payer_action_link(paypal_order)
    except PayPalError as error:
        order.status = OrderStatus.failed
        session.commit()
        raise paypal_error_response("create order", error) from error

    session.commit()

    if order.status == OrderStatus.authorized:
        check_and_decide(session, order, paypal, claude)

    result = OrderCreated.model_validate(order)
    result.payer_action_url = payer_action_url
    return result


@router.post("/{order_id}/authorize", response_model=OrderOut)
def authorize_order(order_id: int, session: DbSession, paypal: PayPal, claude: Claude):
    # the no-vault path: buyer approved at the payer-action link, now place the hold
    order = load_order(session, order_id, lock=True)
    require_status(order, [OrderStatus.created], "authorize")

    try:
        paypal_order = paypal.authorize_order(order.paypal_order_id)
    except PayPalError as error:
        # e.g. 422 ORDER_NOT_APPROVED when the buyer hasn't clicked through yet.
        # leave the order as created so it can be retried
        session.rollback()
        raise paypal_error_response("authorize", error) from error

    authorization = first_authorization(paypal_order)
    if authorization is None:
        order.status = OrderStatus.failed
    else:
        apply_authorization(order, authorization)
    session.commit()

    if order.status == OrderStatus.authorized:
        check_and_decide(session, order, paypal, claude)
    return order


@router.post("/{order_id}/approve", response_model=OrderOut)
def approve_order(order_id: int, body: ReviewDecision, session: DbSession, paypal: PayPal):
    tapped_at = utc_now()
    order = claim_for_review(session, order_id)

    try:
        capture = capture_payment(paypal, order)
    except PAYPAL_FAILURES as error:
        # e.g. 422 AUTHORIZATION_EXPIRED. PayPal's record wins, nothing changes on our side
        logger.exception("PayPal capture failed for order %s", order_id)
        release_claim(session, order_id)
        raise payment_failed(CAPTURE) from error

    approval = build_approval(order_id, ApprovalAction.approve, tapped_at, body.decision_ms)
    try:
        captured = finish_capture(session, order_id, capture, ReviewState.approved, approval)
    except SQLAlchemyError as error:
        session.rollback()
        logger.exception(
            "Order %s was captured at PayPal as %s but saving that failed",
            order_id, capture.get("id"),
        )
        raise save_failed(CAPTURE, order_id) from error

    if not captured:
        logger.error("PayPal declined the capture of order %s", order_id)
        raise HTTPException(
            status_code=502,
            detail={
                "message": "PayPal declined the capture",
                "status": OrderStatus.failed.value,
                "review_state": ReviewState.needs_review.value,
            },
        )
    return order


@router.post("/{order_id}/reject", response_model=OrderOut)
def reject_order(order_id: int, body: ReviewDecision, session: DbSession, paypal: PayPal):
    tapped_at = utc_now()
    order = claim_for_review(session, order_id)

    try:
        voided = paypal.void_authorization(
            order.authorization_id, request_id=payment_request_id(order, VOID)
        )
    except PAYPAL_FAILURES as error:
        logger.exception("PayPal void failed for order %s", order_id)
        release_claim(session, order_id)
        raise payment_failed(VOID) from error

    try:
        order = load_order(session, order_id, lock=True)
        order.status = OrderStatus.voided
        order.review_state = ReviewState.rejected
        # the client asks for the full body so this is normally PayPal's own status, but a 204
        # with no body is also a documented success
        order.void_result = voided.get("status") if voided else "VOIDED"
        order.payment_claimed_at = None
        session.add(
            build_approval(order_id, ApprovalAction.reject, tapped_at, body.decision_ms)
        )
        session.commit()
    except SQLAlchemyError as error:
        session.rollback()
        logger.exception("Order %s was voided at PayPal but saving that failed", order_id)
        raise save_failed(VOID, order_id) from error
    return order


@router.get("", response_model=list[OrderOut])
def list_orders(session: DbSession, limit: int = 50):
    limit = max(1, min(limit, 200))
    # each order's response includes all of these, so load them in one go, not one per row
    query = (
        select(Order)
        .options(
            selectinload(Order.mandate),
            selectinload(Order.decisions),
            selectinload(Order.approvals),
        )
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
    )
    return session.scalars(query).all()


@router.get("/{order_id}", response_model=OrderDetail)
def get_order(order_id: int, session: DbSession):
    return load_order(session, order_id)
