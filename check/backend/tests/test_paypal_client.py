# PayPalClient against mocked PayPal. bodies are trimmed from the Orders v2 /
# Payments v2 schema examples

import socket
import time

import pytest
import requests
import responses

from backend.app.paypal_client import (
    PayPalClient,
    PayPalError,
    first_authorization,
    split_budget,
)

BASE = "https://api-m.sandbox.paypal.com"


@pytest.fixture
def mocked():
    with responses.RequestsMock() as mock:
        mock.add(
            responses.POST,
            BASE + "/v1/oauth2/token",
            json={"access_token": "test-token", "token_type": "Bearer", "expires_in": 32400},
        )
        yield mock


@pytest.fixture
def client():
    return PayPalClient("id", "secret", base_url=BASE)


def request_ids(mock):
    # PayPal-Request-Id on every non-token POST we made
    ids = []
    for call in mock.calls:
        if call.request.method == "POST" and "/oauth2/token" not in call.request.url:
            ids.append(call.request.headers.get("PayPal-Request-Id"))
    return ids


def test_authorize_order(mocked, client):
    mocked.add(
        responses.POST,
        BASE + "/v2/checkout/orders/5O190127TN364715T/authorize",
        status=201,
        json={
            "id": "5O190127TN364715T",
            "status": "COMPLETED",
            "purchase_units": [
                {
                    "payments": {
                        "authorizations": [
                            {
                                "id": "0AW2184448108334S",
                                "status": "CREATED",
                                "amount": {"currency_code": "USD", "value": "42.00"},
                                "expiration_time": "2026-11-20T01:38:09Z",
                            }
                        ]
                    }
                }
            ],
        },
    )

    order = client.authorize_order("5O190127TN364715T")

    auth = first_authorization(order)
    assert auth["id"] == "0AW2184448108334S"
    assert auth["status"] == "CREATED"

    authorize_call = mocked.calls[1].request
    assert authorize_call.headers["Authorization"] == "Bearer test-token"
    assert authorize_call.headers["Prefer"] == "return=representation"
    assert authorize_call.headers["PayPal-Request-Id"]


def test_capture_authorization(mocked, client):
    mocked.add(
        responses.POST,
        BASE + "/v2/payments/authorizations/0AW2184448108334S/capture",
        status=201,
        json={"id": "2GG279541U471931P", "status": "COMPLETED"},
    )

    capture = client.capture_authorization("0AW2184448108334S")

    assert capture["id"] == "2GG279541U471931P"
    assert capture["status"] == "COMPLETED"


def test_void_authorization_204(mocked, client):
    # minimal representation: 204 and no body
    mocked.add(
        responses.POST,
        BASE + "/v2/payments/authorizations/0AW2184448108334S/void",
        status=204,
    )

    assert client.void_authorization("0AW2184448108334S") is None


def test_void_authorization_200(mocked, client):
    mocked.add(
        responses.POST,
        BASE + "/v2/payments/authorizations/0AW2184448108334S/void",
        status=200,
        json={"id": "0AW2184448108334S", "status": "VOIDED"},
    )

    voided = client.void_authorization("0AW2184448108334S")

    assert voided["status"] == "VOIDED"


def test_capture_expired_authorization_raises(mocked, client):
    # straight from the Payments v2 schema example "authorizations_capture_422_expired",
    # PayPal's typo in the name included
    mocked.add(
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

    with pytest.raises(PayPalError) as caught:
        client.capture_authorization("0AW2184448108334S")

    error = caught.value
    assert error.status_code == 422
    assert error.name == "UNPROCCESSABLE_ENTITY"
    assert error.issue == "AUTHORIZATION_EXPIRED"
    assert error.debug_id == "90bff07028f7f"


def test_every_post_gets_a_fresh_request_id(mocked, client):
    mocked.add(
        responses.POST,
        BASE + "/v2/payments/authorizations/A1/capture",
        status=201,
        json={"id": "C1", "status": "COMPLETED"},
    )
    mocked.add(
        responses.POST,
        BASE + "/v2/payments/authorizations/A2/void",
        status=204,
    )

    client.capture_authorization("A1")
    client.void_authorization("A2")

    ids = request_ids(mocked)
    assert len(ids) == 2
    assert ids[0] != ids[1]


def hung_server():
    # accepts connections and never answers, the one thing a mock can't really do
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    return server, "http://127.0.0.1:" + str(server.getsockname()[1])


def test_capture_budget_is_a_real_limit_when_paypal_hangs():
    server, url = hung_server()
    try:
        hanging_client = PayPalClient("id", "secret", base_url=url)
        hanging_client._token = "cached"
        hanging_client._token_expires_at = time.time() + 1000

        started = time.monotonic()
        with pytest.raises(requests.Timeout):
            hanging_client.capture_authorization("A1", budget_seconds=0.5)
        elapsed = time.monotonic() - started
    finally:
        server.close()

    assert elapsed < 2


def test_capture_budget_covers_fetching_a_token():
    # it can't turn into 15 seconds for the token and another 15 for the capture
    server, url = hung_server()
    try:
        hanging_client = PayPalClient("id", "secret", base_url=url)

        started = time.monotonic()
        with pytest.raises(requests.Timeout):
            hanging_client.capture_authorization("A1", budget_seconds=0.5)
        elapsed = time.monotonic() - started
    finally:
        server.close()

    assert elapsed < 2


def test_budget_is_split_so_it_adds_up_to_what_was_asked():
    assert split_budget(15) == (3, 12)
    assert split_budget(2) == (1, 1)


def test_capture_without_a_budget_uses_the_normal_timeout(mocked, client):
    mocked.add(
        responses.POST,
        BASE + "/v2/payments/authorizations/A1/capture",
        status=201,
        json={"id": "C1", "status": "COMPLETED"},
    )

    client.capture_authorization("A1")

    assert mocked.calls[-1].request.req_kwargs["timeout"] == 30


def test_caller_can_pass_its_own_request_id(mocked, client):
    # so a retry can reuse the id we stored and PayPal won't double-capture
    mocked.add(
        responses.POST,
        BASE + "/v2/payments/authorizations/A1/capture",
        status=201,
        json={"id": "C1", "status": "COMPLETED"},
    )

    client.capture_authorization("A1", request_id="leash-capture-order-7")

    assert request_ids(mocked) == ["leash-capture-order-7"]


def test_get_capture(mocked, client):
    mocked.add(
        responses.GET,
        BASE + "/v2/payments/captures/2GG279541U471931P",
        json={"id": "2GG279541U471931P", "status": "COMPLETED"},
    )

    assert client.get_capture("2GG279541U471931P")["status"] == "COMPLETED"


def test_token_is_cached(mocked, client):
    mocked.add(
        responses.GET,
        BASE + "/v2/payments/authorizations/A1",
        json={"id": "A1", "status": "CREATED"},
    )

    client.get_authorization("A1")
    client.get_authorization("A1")

    token_calls = 0
    for call in mocked.calls:
        if "/oauth2/token" in call.request.url:
            token_calls += 1
    assert token_calls == 1
