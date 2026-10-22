# Agent orders: create (PayPal intent AUTHORIZE), authorize, capture, void, list, read.
#
# Money flow is what the spikes proved in sandbox:
#   spike 1: create -> buyer approves -> authorize -> capture or void
#   spike 2: create with payment_source.paypal.vault_id -> comes back already authorized,
#            no buyer action. falls back to /authorize if it ever doesn't
#
# Status moves one way only:
#   created -> authorized -> captured
#                         -> voided
#   any PayPal failure while creating/authorizing -> failed

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.db import get_session
from backend.app.models import ApprovalAction, CheckedBy, Mandate, Order, OrderStatus, Verdict
from backend.app.paypal_client import PayPalError, client_from_settings, first_authorization

router = APIRouter(prefix="/orders", tags=["orders"])

CENT = Decimal("0.01")
CURRENCY = "USD"
STORE_NAME = "Fernwood Supply Co"


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


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mandate_id: int
    paypal_order_id: str | None
    authorization_id: str | None
    capture_id: str | None
    vault_id: str | None
    items: list
    total: Decimal
    currency: str
    status: OrderStatus
    authorization_expires_at: datetime | None
    created_at: datetime


class OrderCreated(OrderOut):
    # only set when there's no vault id: the buyer has to open this and approve
    payer_action_url: str | None = None


class MandateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    buyer_label: str
    raw_request: str
    rules: dict
    max_price: Decimal | None
    merchant: str | None
    expires_at: datetime | None
    created_at: datetime


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    verdict: Verdict
    risk_score: int | None
    reason: str
    checked_by: CheckedBy
    created_at: datetime


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: ApprovalAction | None
    decided_by: str | None
    opened_at: datetime | None
    decided_at: datetime | None
    decision_ms: int | None


class OrderDetail(OrderOut):
    mandate: MandateSummary
    decisions: list[DecisionOut]
    approvals: list[ApprovalOut]


# ---- dependencies ----


@lru_cache
def get_paypal_client():
    # one client for the whole app so the OAuth token cache is shared between requests
    return client_from_settings(get_settings())


DbSession = Annotated[Session, Depends(get_session)]
PayPal = Annotated[object, Depends(get_paypal_client)]


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
    else:
        order.status = OrderStatus.failed


def load_order(session, order_id, lock=False):
    query = select(Order).where(Order.id == order_id)
    if lock:
        # row lock on Postgres so two capture/void calls can't both pass the status check
        query = query.with_for_update()
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


def run_intent_check(session, order):
    # ================================================================================
    # TODO(intent check): this is where Leash checks the order against the mandate.
    # The money is authorized but not captured at this point. The check will:
    #   1. compare order.items / order.total with order.mandate.rules (rules first,
    #      Claude for anything fuzzy) and save a Decision row
    #   2. clean match -> capture right away
    #   3. anything off -> leave it authorized and open an Approval for the human
    # For now every order just stays authorized and waits for a manual capture/void.
    # ================================================================================
    return None


# ---- endpoints ----


@router.post("", response_model=OrderCreated, status_code=201)
def create_order(body: OrderCreate, session: DbSession, paypal: PayPal):
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
        run_intent_check(session, order)

    result = OrderCreated.model_validate(order)
    result.payer_action_url = payer_action_url
    return result


@router.post("/{order_id}/authorize", response_model=OrderOut)
def authorize_order(order_id: int, session: DbSession, paypal: PayPal):
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
        run_intent_check(session, order)
    return order


@router.post("/{order_id}/capture", response_model=OrderOut)
def capture_order(order_id: int, session: DbSession, paypal: PayPal):
    order = load_order(session, order_id, lock=True)
    require_status(order, [OrderStatus.authorized], "capture")

    try:
        capture = paypal.capture_authorization(order.authorization_id)
    except PayPalError as error:
        # e.g. 422 AUTHORIZATION_EXPIRED. status stays authorized, PayPal's record wins
        session.rollback()
        raise paypal_error_response("capture", error) from error

    order.capture_id = capture.get("id")
    if capture.get("status") == "DECLINED":
        order.status = OrderStatus.failed
    else:
        # COMPLETED, or PENDING while PayPal finishes. either way the money is taken
        order.status = OrderStatus.captured
    session.commit()
    return order


@router.post("/{order_id}/void", response_model=OrderOut)
def void_order(order_id: int, session: DbSession, paypal: PayPal):
    order = load_order(session, order_id, lock=True)
    require_status(order, [OrderStatus.authorized], "void")

    try:
        paypal.void_authorization(order.authorization_id)
    except PayPalError as error:
        session.rollback()
        raise paypal_error_response("void", error) from error

    order.status = OrderStatus.voided
    session.commit()
    return order


@router.get("", response_model=list[OrderOut])
def list_orders(session: DbSession, limit: int = 50):
    limit = max(1, min(limit, 200))
    query = select(Order).order_by(Order.created_at.desc(), Order.id.desc()).limit(limit)
    return session.scalars(query).all()


@router.get("/{order_id}", response_model=OrderDetail)
def get_order(order_id: int, session: DbSession):
    return load_order(session, order_id)
