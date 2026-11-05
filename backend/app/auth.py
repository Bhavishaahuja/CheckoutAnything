# The two API keys. Demo-grade on purpose, see "Security model" in the README.
#   agent key:    what the shopping agent holds. it can create mandates and orders, nothing else
#   merchant key: what the dashboard holds. it reads orders and creates review links
#
# A human approving on their phone has neither. They hold a review link, see review.py.

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader

from backend.app.config import get_settings

API_KEY_HEADER = "X-API-Key"

# auto_error off so a missing key gets the same 401 as a wrong one, FastAPI would send a 403
api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)
ProvidedKey = Annotated[str | None, Depends(api_key_header)]


def check_key(provided, expected):
    # an unset key on the server has to lock the door, not leave it open: without this an empty
    # header would match an empty setting. compare_digest so timing doesn't leak the key
    if not expected or not provided:
        raise unauthorized()
    if not secrets.compare_digest(provided.encode(), expected.encode()):
        raise unauthorized()


def unauthorized():
    return HTTPException(status_code=401, detail="Missing or wrong API key")


def require_agent(provided: ProvidedKey):
    check_key(provided, get_settings().agent_api_key)


def require_merchant(provided: ProvidedKey):
    check_key(provided, get_settings().merchant_api_key)
