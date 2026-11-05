# Dashboard login and session tokens. The merchant routes accepting them is in test_orders.py

import hashlib
import hmac
import time
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from keyed_client import AGENT_KEY, DEMO_PASSWORD, MERCHANT_KEY

from backend.app import auth, session
from backend.app.auth import issue_session_token, require_merchant, session_token_is_valid
from backend.app.config import get_settings
from backend.app.session import RateLimiter


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(session.router)

    @app.get("/merchant-only", dependencies=[Depends(require_merchant)])
    def merchant_only():
        return {"ok": True}

    return TestClient(app)


def login(client, password=DEMO_PASSWORD, headers=None):
    return client.post("/auth/session", json={"password": password}, headers=headers)


def bearer(token):
    return {"Authorization": "Bearer " + token}


# ---- logging in ----


def test_right_password_gets_a_working_token_for_8_hours(client):
    # whole seconds, the same as the token's expiry
    started = int(time.time())

    response = login(client)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"session_token", "expires_at"}
    expires = int(body["session_token"].split(".")[0])
    assert 8 * 3600 <= expires - started <= 8 * 3600 + 5
    assert client.get("/merchant-only", headers=bearer(body["session_token"])).status_code == 200


@pytest.mark.parametrize("password", ["wrong", MERCHANT_KEY, AGENT_KEY, DEMO_PASSWORD + "x"])
def test_wrong_password_is_a_401(client, password):
    response = login(client, password)

    assert response.status_code == 401
    assert "session_token" not in response.text


def test_empty_password_is_refused(client):
    assert login(client, "").status_code == 422


def test_unset_password_turns_login_off(client, monkeypatch):
    # a forgotten env var has to fail closed
    monkeypatch.setenv("DEMO_MERCHANT_PASSWORD", "")
    get_settings.cache_clear()

    assert login(client, "anything").status_code == 401


def test_no_merchant_key_means_no_sessions(client, monkeypatch):
    # nothing to sign with. the password can be right and it still can't hand out a token
    monkeypatch.setenv("MERCHANT_API_KEY", "")
    get_settings.cache_clear()

    assert login(client).status_code == 401


def test_session_token_isnt_the_merchant_key_or_password(client):
    token = login(client).json()["session_token"]

    assert MERCHANT_KEY not in token
    assert DEMO_PASSWORD not in token


# ---- what a token is worth ----


def test_expired_token_fails():
    # issued 8 hours and a second ago
    token, _ = issue_session_token(now=time.time() - 8 * 3600 - 1)

    assert session_token_is_valid(token) is False


def test_token_is_good_until_just_before_it_expires():
    now = 1000000
    token, expires_at = issue_session_token(now=now)

    assert session_token_is_valid(token, now=expires_at - 1) is True
    assert session_token_is_valid(token, now=expires_at) is False


def test_cant_extend_a_token_by_editing_it():
    token, expires_at = issue_session_token()
    signature = token.split(".")[1]

    assert session_token_is_valid(str(expires_at + 86400) + "." + signature) is False


@pytest.mark.parametrize("token", [
    "", ".", "garbage", "abc.def", "123", "123.", ".abc", "٣٣٣.abc", "-1.abc", "1.2.3",
    AGENT_KEY, MERCHANT_KEY, DEMO_PASSWORD,
])
def test_malformed_tokens_fail(token):
    assert session_token_is_valid(token) is False


def test_changing_the_merchant_key_ends_all_sessions(monkeypatch):
    token, _ = issue_session_token()
    assert session_token_is_valid(token) is True

    monkeypatch.setenv("MERCHANT_API_KEY", "a-different-key")
    get_settings.cache_clear()

    assert session_token_is_valid(token) is False


def test_merchant_route_takes_either_kind_of_credential(client):
    token = login(client).json()["session_token"]

    assert client.get("/merchant-only").status_code == 401
    assert client.get("/merchant-only", headers=bearer(token)).status_code == 200
    assert client.get("/merchant-only", headers={"X-API-Key": MERCHANT_KEY}).status_code == 200
    # a bad token doesn't cancel out a good key, it just isn't what got it in
    both = {"X-API-Key": MERCHANT_KEY, "Authorization": "Bearer nope"}
    assert client.get("/merchant-only", headers=both).status_code == 200


@pytest.mark.parametrize("value", ["nope", AGENT_KEY, MERCHANT_KEY, DEMO_PASSWORD])
def test_things_that_arent_session_tokens_fail_as_bearer(client, value):
    assert client.get("/merchant-only", headers=bearer(value)).status_code == 401


def test_non_ascii_credentials_are_a_401_not_a_crash(client):
    # httpx won't send non-ascii headers from a str, so these go in as raw bytes
    assert client.get(
        "/merchant-only", headers={"Authorization": "Bearer ünicode.tøken".encode()}
    ).status_code == 401


# ---- rate limit ----


def test_eleventh_try_in_a_minute_is_a_429(client):
    for _ in range(10):
        assert login(client, "wrong").status_code == 401

    response = login(client, "wrong")

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1


def test_right_password_is_also_blocked_once_limited(client):
    # otherwise the limit would tell an attacker which guess was right
    for _ in range(10):
        login(client, "wrong")

    assert login(client).status_code == 429


def test_right_passwords_count_as_tries_too(client):
    for _ in range(10):
        assert login(client).status_code == 200

    assert login(client).status_code == 429


def test_limit_is_per_address(client):
    for _ in range(10):
        login(client, "wrong", headers={"X-Forwarded-For": "203.0.113.1"})

    assert login(client, "wrong", headers={"X-Forwarded-For": "203.0.113.1"}).status_code == 429
    assert login(client, "wrong", headers={"X-Forwarded-For": "203.0.113.2"}).status_code == 401


def test_cant_dodge_the_limit_by_making_up_a_forwarded_address(client):
    # the proxy adds the real address last, so changing what's in front of it gets nowhere
    for number in range(10):
        made_up = "10.0.0." + str(number) + ", 203.0.113.1"
        login(client, "wrong", headers={"X-Forwarded-For": made_up})

    response = login(client, "wrong", headers={"X-Forwarded-For": "10.9.9.9, 203.0.113.1"})

    assert response.status_code == 429


def test_tries_age_out_of_the_window():
    limiter = RateLimiter(max_tries=2, window_seconds=60)

    assert limiter.seconds_until_allowed("a", now=0) == 0
    assert limiter.seconds_until_allowed("a", now=10) == 0
    assert limiter.seconds_until_allowed("a", now=20) == 40
    # the first one has aged out, the blocked one above never counted
    assert limiter.seconds_until_allowed("a", now=60) == 0


def test_limiter_memory_cant_grow_forever(monkeypatch):
    monkeypatch.setattr(session, "MAX_TRACKED_ADDRESSES", 3)
    limiter = RateLimiter(max_tries=2, window_seconds=60)

    for number in range(10):
        limiter.seconds_until_allowed("address-" + str(number), now=0)

    assert len(limiter.tries_by_address) <= 3


# ---- keeping the key out of the browser ----


def test_nothing_in_the_frontend_mentions_a_server_secret():
    # anything in the bundle is readable by whoever loads the page, so the dashboard logs in
    frontend = Path("frontend")
    names = ["MERCHANT_API_KEY", "AGENT_API_KEY", "DEMO_MERCHANT_PASSWORD", "X-API-Key"]
    checked = 0
    for pattern in ["src/**/*", ".env.example", "index.html", "vite.config.*"]:
        for path in frontend.glob(pattern):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                for name in names:
                    assert name not in text, name + " is in " + str(path)
                checked += 1
    # if the frontend moved, this can't just pass by looking at nothing
    assert checked > 5


def test_signature_uses_a_derived_key_not_the_merchant_key_directly():
    # the merchant key is what scripts authenticate with, so it isn't used to sign anything as is
    token, expires_at = issue_session_token()
    signature = token.split(".")[1]

    direct = hmac.new(MERCHANT_KEY.encode(), str(expires_at).encode(), hashlib.sha256).hexdigest()

    assert signature != direct
    assert signature == auth.session_signature(expires_at)
