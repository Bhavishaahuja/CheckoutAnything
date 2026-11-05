# POST /auth/session: the dashboard's login. One shared demo password, no accounts. It trades the
# password for a session token that lasts 8 hours, so the merchant key never reaches a browser.

import logging
import secrets
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.app.auth import issue_session_token
from backend.app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_TRIES = 10
WINDOW_SECONDS = 60
# only reached under a flood of different addresses, and forgetting them just resets their counts
MAX_TRACKED_ADDRESSES = 10000


class RateLimiter:
    # sliding window in memory: per process and gone on restart, which is fine for a demo.
    # the lock is because FastAPI runs these requests on a thread pool

    def __init__(self, max_tries, window_seconds):
        self.max_tries = max_tries
        self.window_seconds = window_seconds
        self.tries_by_address = {}
        self.lock = threading.Lock()

    def seconds_until_allowed(self, address, now=None):
        # counts this try and returns 0 if it's allowed, otherwise how long until one is
        if now is None:
            now = time.monotonic()

        with self.lock:
            if len(self.tries_by_address) >= MAX_TRACKED_ADDRESSES:
                self.tries_by_address.clear()

            recent = []
            for tried_at in self.tries_by_address.get(address, []):
                if now - tried_at < self.window_seconds:
                    recent.append(tried_at)

            if len(recent) >= self.max_tries:
                self.tries_by_address[address] = recent
                return self.window_seconds - (now - recent[0])

            recent.append(now)
            self.tries_by_address[address] = recent
            return 0

    def reset(self):
        with self.lock:
            self.tries_by_address.clear()


login_limiter = RateLimiter(MAX_TRIES, WINDOW_SECONDS)


class LoginBody(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class SessionOut(BaseModel):
    session_token: str
    expires_at: datetime


def client_address(request):
    # on Render every request arrives from its proxy, so the real address is in X-Forwarded-For.
    # the last entry is the one the proxy added itself. anything before it came from the client
    # and could be made up to dodge the limit
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    if request.client:
        return request.client.host
    return "unknown"


@router.post("/session", response_model=SessionOut)
def create_session(body: LoginBody, request: Request):
    # counted before looking at the password, so a right guess and a wrong one cost the same
    wait = login_limiter.seconds_until_allowed(client_address(request))
    if wait > 0:
        logger.warning("Too many login attempts from one address")
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts, try again in a minute",
            headers={"Retry-After": str(int(wait) + 1)},
        )

    # an unset password turns login off, an empty one can't match anything
    expected = get_settings().demo_merchant_password
    matches = bool(expected) and secrets.compare_digest(body.password.encode(), expected.encode())
    if not matches:
        raise HTTPException(status_code=401, detail="Wrong password")

    token, expires_at = issue_session_token()
    if token is None:
        # MERCHANT_API_KEY isn't set. nothing to sign with, so no sessions
        logger.error("Login refused: MERCHANT_API_KEY isn't set")
        raise HTTPException(status_code=401, detail="Wrong password")

    return SessionOut(
        session_token=token,
        expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
    )
