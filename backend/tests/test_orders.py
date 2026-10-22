# Order endpoints with PayPal mocked (responses) and SQLite. The PayPal bodies are trimmed
# from the Orders v2 / Payments v2 schema examples and what spikes 1 + 2 got back in sandbox

import json
from decimal import Decimal

import pytest
import responses
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import orders
from backend.app.db import Base, get_session
from backend.app.models import Approval, CheckedBy, Decision, Mandate, Verdict
from backend.app.paypal_client import PayPalClient

BASE = "https://api-m.sandbox.paypal.com"
VAULT_ID = "test-vault-id"

ORDER_BODY = {
    "mandate_id": 1,
    "items": [
        {"name": "Trail runner", "color": "black", "size": "9", "quantity": 1,
         "unit_price": "42.00"},
        {"name": "Wool hiking socks", "quantity": 2, "unit_price": "9.50"},
    ],
    "shipping": "5.00",
}


def authorized_paypal_order(order_id, authorization_id, amount="66.00"):
    # what a vault_id + AUTHORIZE create (or an /authorize call) returns: COMPLETED,
    # with the authorization already inside
    return {
        "id": order_id,
        "status": "COMPLETED",
        "purchase_units": [{
            "payments": {
                "authorizations": [{
                    "id": authorization_id,
                    "status": "CREATED",
                    "amount": {"currency_code": "USD", "value": amount},
                    "expiration_time": "2026-11-20T01:56:55Z",
                }]
            }
        }],
    }


def payer_action_paypal_order(order_id):
    return {
        "id": order_id,
        "status": "PAYER_ACTION_REQUIRED",
        "links": [
            {"href": BASE + "/v2/checkout/orders/" + order_id, "rel": "self", "method": "GET"},
            {"href": "https://www.sandbox.paypal.com/checkoutnow?token=" + order_id,
             "rel": "payer-action", "method": "GET"},
        ],
    }


@pytest.fixture
def paypal():
    # tests that never reach PayPal (404s, 409s) won't use the token mock, that's fine
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add(
            responses.POST,
            BASE + "/v1/oauth2/token",
            json={"access_token": "test-token", "expires_in": 32400},
        )
        yield mock


@pytest.fixture
def db_sessions():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        session.add(Mandate(
            id=1,
            buyer_label="Sam",
            raw_request="Trail runners and socks under $100 from Fernwood Supply Co",
            rules={"max_price": 100},
            max_price=Decimal("100.00"),
            merchant="Fernwood Supply Co",
        ))
        session.commit()
    return sessions


@pytest.fixture
def client(db_sessions, paypal):
    app = FastAPI()
    app.include_router(orders.router)

    def test_session():
        session = db_sessions()
        try:
            yield session
        finally:
            session.close()

    paypal_client = PayPalClient("id", "secret", base_url=BASE)
    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[orders.get_paypal_client] = lambda: paypal_client
    return TestClient(app)


def sent_json(paypal, url_part):
    # body of the last request we sent to a PayPal URL containing url_part
    for call in reversed(paypal.calls):
        if url_part in call.request.url and call.request.body:
            return json.loads(call.request.body)
    return None


def create_vault_order(client, paypal, paypal_order_id="5O190127TN364715T",
                       authorization_id="0AW2184448108334S"):
    paypal.add(
        responses.POST,
        BASE + "/v2/checkout/orders",
        status=201,
        json=authorized_paypal_order(paypal_order_id, authorization_id),
    )
    body = dict(ORDER_BODY)
    body["vault_id"] = VAULT_ID
    response = client.post("/orders", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def create_unapproved_order(client, paypal, paypal_order_id="8XU44448NV0000000"):
    paypal.add(
        responses.POST,
        BASE + "/v2/checkout/orders",
        status=201,
        json=payer_action_paypal_order(paypal_order_id),
    )
    response = client.post("/orders", json=ORDER_BODY)
    assert response.status_code == 201, response.text
    return response.json()


def mock_capture(paypal, authorization_id="0AW2184448108334S", capture_id="2GG279541U471931P"):
    paypal.add(
        responses.POST,
        BASE + "/v2/payments/authorizations/" + authorization_id + "/capture",
        status=201,
        json={"id": capture_id, "status": "COMPLETED"},
    )


def mock_void(paypal, authorization_id="0AW2184448108334S"):
    paypal.add(
        responses.POST,
        BASE + "/v2/payments/authorizations/" + authorization_id + "/void",
        status=204,
    )


# ---- happy paths ----


def test_vault_order_is_authorized_then_captured(client, paypal):
    order = create_vault_order(client, paypal)

    assert order["status"] == "authorized"
    assert order["paypal_order_id"] == "5O190127TN364715T"
    assert order["authorization_id"] == "0AW2184448108334S"
    assert order["authorization_expires_at"].startswith("2026-11-20T01:56:55")
    assert order["vault_id"] == VAULT_ID
    assert order["payer_action_url"] is None
    # 42.00 + 2 x 9.50 + 5.00 shipping
    assert order["total"] == "66.00"

    # what we sent PayPal: spike 2's vault shape, and amounts that add up
    sent = sent_json(paypal, "/v2/checkout/orders")
    assert sent["intent"] == "AUTHORIZE"
    assert sent["payment_source"]["paypal"]["vault_id"] == VAULT_ID
    assert sent["payment_source"]["paypal"]["stored_credential"]["payment_initiator"] == "MERCHANT"
    unit = sent["purchase_units"][0]
    assert unit["amount"]["value"] == "66.00"
    assert unit["amount"]["breakdown"]["item_total"]["value"] == "61.00"
    assert unit["amount"]["breakdown"]["shipping"]["value"] == "5.00"
    assert unit["items"][0]["name"] == "Trail runner, black, size 9"
    assert unit["items"][1]["quantity"] == "2"
    assert unit["custom_id"] == str(order["id"])

    mock_capture(paypal)
    captured = client.post("/orders/" + str(order["id"]) + "/capture")

    assert captured.status_code == 200
    assert captured.json()["status"] == "captured"
    assert captured.json()["capture_id"] == "2GG279541U471931P"


def test_vault_order_then_void(client, paypal):
    order = create_vault_order(client, paypal)

    mock_void(paypal)
    voided = client.post("/orders/" + str(order["id"]) + "/void")

    assert voided.status_code == 200
    assert voided.json()["status"] == "voided"


def test_vault_order_falls_back_to_authorize(client, paypal):
    # spike 2's fallback: if create ever comes back without an authorization, authorize it
    paypal.add(
        responses.POST,
        BASE + "/v2/checkout/orders",
        status=201,
        json={"id": "5O190127TN364715T", "status": "APPROVED"},
    )
    paypal.add(
        responses.POST,
        BASE + "/v2/checkout/orders/5O190127TN364715T/authorize",
        status=201,
        json=authorized_paypal_order("5O190127TN364715T", "0AW2184448108334S"),
    )
    body = dict(ORDER_BODY)
    body["vault_id"] = VAULT_ID

    response = client.post("/orders", json=body)

    assert response.json()["status"] == "authorized"
    assert response.json()["authorization_id"] == "0AW2184448108334S"


def test_no_vault_returns_payer_action_link_then_authorizes(client, paypal):
    order = create_unapproved_order(client, paypal)

    assert order["status"] == "created"
    assert order["authorization_id"] is None
    assert order["payer_action_url"] == (
        "https://www.sandbox.paypal.com/checkoutnow?token=8XU44448NV0000000"
    )
    sent = sent_json(paypal, "/v2/checkout/orders")
    assert "vault_id" not in sent["payment_source"]["paypal"]
    assert sent["payment_source"]["paypal"]["experience_context"]["brand_name"] == (
        "Fernwood Supply Co"
    )

    # buyer approved in the browser, now place the hold
    paypal.add(
        responses.POST,
        BASE + "/v2/checkout/orders/8XU44448NV0000000/authorize",
        status=201,
        json=authorized_paypal_order("8XU44448NV0000000", "7PS21555RT234531W"),
    )
    authorized = client.post("/orders/" + str(order["id"]) + "/authorize")

    assert authorized.status_code == 200
    assert authorized.json()["status"] == "authorized"
    assert authorized.json()["authorization_id"] == "7PS21555RT234531W"


# ---- illegal transitions ----


def test_cant_capture_a_voided_order(client, paypal):
    order = create_vault_order(client, paypal)
    mock_void(paypal)
    client.post("/orders/" + str(order["id"]) + "/void")

    response = client.post("/orders/" + str(order["id"]) + "/capture")

    assert response.status_code == 409
    assert "was voided" in response.json()["detail"]


def test_cant_void_a_captured_order(client, paypal):
    order = create_vault_order(client, paypal)
    mock_capture(paypal)
    client.post("/orders/" + str(order["id"]) + "/capture")

    response = client.post("/orders/" + str(order["id"]) + "/void")

    assert response.status_code == 409
    assert "already captured" in response.json()["detail"]


def test_cant_capture_or_void_before_authorized(client, paypal):
    order = create_unapproved_order(client, paypal)

    capture = client.post("/orders/" + str(order["id"]) + "/capture")
    void = client.post("/orders/" + str(order["id"]) + "/void")

    assert capture.status_code == 409
    assert "isn't authorized yet" in capture.json()["detail"]
    assert void.status_code == 409
    # and PayPal was never asked to capture or void anything
    for call in paypal.calls:
        assert "/capture" not in call.request.url
        assert "/void" not in call.request.url


def test_cant_authorize_twice(client, paypal):
    order = create_vault_order(client, paypal)

    response = client.post("/orders/" + str(order["id"]) + "/authorize")

    assert response.status_code == 409


# ---- PayPal errors and missing things ----


def test_paypal_422_is_a_clean_error(client, paypal):
    order = create_vault_order(client, paypal)
    # Payments v2 schema example "authorizations_capture_422_expired"
    paypal.add(
        responses.POST,
        BASE + "/v2/payments/authorizations/0AW2184448108334S/capture",
        status=422,
        json={
            "name": "UNPROCCESSABLE_ENTITY",
            "message": "The requested action could not be completed, is semantically "
            "incorrect, or failed business validation.",
            "debug_id": "90bff07028f7f",
            "details": [
                {"issue": "AUTHORIZATION_EXPIRED", "description": "The authorization has expired."}
            ],
        },
    )

    response = client.post("/orders/" + str(order["id"]) + "/capture")

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["paypal_status"] == 422
    assert detail["paypal_issue"] == "AUTHORIZATION_EXPIRED"
    assert detail["debug_id"] == "90bff07028f7f"
    # nothing changed on our side
    assert client.get("/orders/" + str(order["id"])).json()["status"] == "authorized"


def test_paypal_error_on_create_marks_order_failed(client, paypal):
    paypal.add(
        responses.POST,
        BASE + "/v2/checkout/orders",
        status=422,
        json={
            "name": "UNPROCESSABLE_ENTITY",
            "debug_id": "abc123",
            "details": [{"issue": "PAYEE_ACCOUNT_RESTRICTED"}],
        },
    )
    body = dict(ORDER_BODY)
    body["vault_id"] = VAULT_ID

    response = client.post("/orders", json=body)

    assert response.status_code == 502
    assert response.json()["detail"]["paypal_issue"] == "PAYEE_ACCOUNT_RESTRICTED"
    saved = client.get("/orders").json()
    assert saved[0]["status"] == "failed"


def test_missing_order_is_404(client):
    assert client.get("/orders/999").status_code == 404
    assert client.post("/orders/999/capture").status_code == 404
    assert client.post("/orders/999/void").status_code == 404
    assert client.post("/orders/999/authorize").status_code == 404


def test_missing_mandate_is_404(client):
    body = dict(ORDER_BODY)
    body["mandate_id"] = 999

    assert client.post("/orders", json=body).status_code == 404


# ---- reading ----


def test_list_is_newest_first(client, paypal):
    first = create_vault_order(client, paypal, "ORDER1", "AUTH1")
    second = create_vault_order(client, paypal, "ORDER2", "AUTH2")

    listed = client.get("/orders").json()

    ids = []
    for order in listed:
        ids.append(order["id"])
    assert ids == [second["id"], first["id"]]


def test_get_order_includes_mandate_decisions_and_approvals(client, paypal, db_sessions):
    order = create_vault_order(client, paypal)
    with db_sessions() as session:
        session.add(Decision(
            order_id=order["id"],
            verdict=Verdict.mismatch,
            risk_score=70,
            reason="Socks weren't in the mandate.",
            checked_by=CheckedBy.rules,
        ))
        session.add(Approval(order_id=order["id"]))
        session.commit()

    detail = client.get("/orders/" + str(order["id"])).json()

    assert detail["mandate"]["merchant"] == "Fernwood Supply Co"
    assert detail["decisions"][0]["verdict"] == "mismatch"
    assert detail["decisions"][0]["reason"] == "Socks weren't in the mandate."
    assert detail["approvals"][0]["action"] is None
    assert detail["items"][0]["name"] == "Trail runner"


def test_main_app_serves_order_routes():
    from backend.app.main import app

    paths = app.openapi()["paths"]
    assert "post" in paths["/orders"]
    assert "get" in paths["/orders"]
    assert "post" in paths["/orders/{order_id}/capture"]
    assert "post" in paths["/orders/{order_id}/void"]
    assert "post" in paths["/orders/{order_id}/authorize"]
    assert "get" in paths["/orders/{order_id}"]
