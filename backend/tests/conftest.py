# Every test runs with known API keys, whatever is or isn't in the local .env

import pytest

from backend.app.config import get_settings
from keyed_client import AGENT_KEY, MERCHANT_KEY


@pytest.fixture(autouse=True)
def api_keys(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEY", AGENT_KEY)
    monkeypatch.setenv("MERCHANT_API_KEY", MERCHANT_KEY)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
