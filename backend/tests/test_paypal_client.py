import json

import pytest
import responses

from backend.app.paypal_client import (
    PayPalClient,
    PayPalError,
    build_order_body,
    describe_failure,
    first_capture,
)

BASE = "https://api-m.sandbox.paypal.com"


def add_token(expires_in=3600):
    responses.post(BASE + "/v1/oauth2/token",
                   json={"access_token": "token-1", "expires_in": expires_in})


@responses.activate
def test_token_is_fetched_once_and_reused():
    add_token()
    responses.get(BASE + "/v2/checkout/orders/A1", json={"id": "A1"})
    client = PayPalClient("id", "secret")
    client.get_order("A1")
    client.get_order("A1")
    token_calls = [call for call in responses.calls if "oauth2" in call.request.url]
    assert len(token_calls) == 1
    assert responses.calls[1].request.headers["Authorization"] == "Bearer token-1"


@responses.activate
def test_an_expiring_token_is_fetched_again():
    # 30 seconds left is inside the 60 second margin, so it counts as expired already
    add_token(expires_in=30)
    add_token(expires_in=30)
    responses.get(BASE + "/v2/checkout/orders/A1", json={"id": "A1"})
    client = PayPalClient("id", "secret")
    client.get_order("A1")
    client.get_order("A1")
    token_calls = [call for call in responses.calls if "oauth2" in call.request.url]
    assert len(token_calls) == 2


@responses.activate
def test_create_order_sends_a_request_id_and_asks_for_the_full_order():
    add_token()
    responses.post(BASE + "/v2/checkout/orders", json={"id": "A1", "status": "CREATED"},
                   status=201)
    client = PayPalClient("id", "secret")
    client.create_order({"intent": "CAPTURE"})
    client.create_order({"intent": "CAPTURE"}, request_id="mine")
    first = responses.calls[1].request
    second = responses.calls[2].request
    assert first.headers["Prefer"] == "return=representation"
    assert first.headers["PayPal-Request-Id"]
    assert first.headers["PayPal-Request-Id"] != second.headers["PayPal-Request-Id"]
    assert second.headers["PayPal-Request-Id"] == "mine"
    assert json.loads(first.body) == {"intent": "CAPTURE"}


@responses.activate
def test_paypal_errors_keep_the_issue_and_debug_id():
    add_token()
    responses.post(BASE + "/v2/checkout/orders", status=422, json={
        "name": "UNPROCESSABLE_ENTITY", "message": "Semantically incorrect",
        "debug_id": "abc123", "details": [{"issue": "AMOUNT_MISMATCH", "description": "x"}],
    })
    client = PayPalClient("id", "secret")
    with pytest.raises(PayPalError) as error:
        client.create_order({})
    assert error.value.status_code == 422
    assert error.value.issue == "AMOUNT_MISMATCH"
    assert "abc123" in describe_failure(error.value)


@responses.activate
def test_bad_credentials_raise():
    responses.post(BASE + "/v1/oauth2/token", status=401,
                   json={"error": "invalid_client", "error_description": "Client auth failed"})
    client = PayPalClient("id", "wrong")
    with pytest.raises(PayPalError) as error:
        client.get_order("A1")
    assert error.value.name == "invalid_client"


def test_missing_credentials_raise_without_a_network_call():
    client = PayPalClient("", "")
    with pytest.raises(PayPalError) as error:
        client.get_token()
    assert "PAYPAL_CLIENT_ID" in str(error.value)


def test_live_paypal_is_refused():
    with pytest.raises(ValueError):
        PayPalClient("id", "secret", base_url="https://api-m.paypal.com")


def test_order_body_adds_up_the_way_paypal_requires():
    body = build_order_body("USD", "Sourdough Loaf (Half loaf) + Sliced", "6.00", 3, "6.00",
                            vault_id="vault-1")
    unit = body["purchase_units"][0]
    assert unit["items"][0]["quantity"] == "3"
    assert unit["items"][0]["unit_amount"] == {"currency_code": "USD", "value": "6.00"}
    assert unit["amount"]["breakdown"]["item_total"]["value"] == "18.00"
    assert unit["amount"]["breakdown"]["shipping"]["value"] == "6.00"
    assert unit["amount"]["value"] == "24.00"
    assert body["payment_source"]["paypal"]["vault_id"] == "vault-1"
    assert body["payment_source"]["paypal"]["stored_credential"]["payment_initiator"] == \
        "MERCHANT"


def test_order_body_without_shipping_or_vault():
    body = build_order_body("USD", "Headshot", "40.00", 1, "0.00")
    unit = body["purchase_units"][0]
    assert "shipping" not in unit["amount"]["breakdown"]
    assert unit["amount"]["value"] == "40.00"
    assert "payment_source" not in body


def test_first_capture_handles_orders_with_no_payment():
    assert first_capture({"purchase_units": [{"amount": {}}]}) is None
    assert first_capture({}) is None
    order = {"purchase_units": [{"payments": {"captures": [{"id": "C1"}]}}]}
    assert first_capture(order) == {"id": "C1"}
