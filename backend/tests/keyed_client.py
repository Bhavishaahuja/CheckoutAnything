# A test client that sends the key each route is meant to get, so the tests that aren't about auth
# can stay about what they're about. Auth itself is tested with a plain TestClient and explicit
# headers, in test_orders.py.

from fastapi.testclient import TestClient

AGENT_KEY = "test-agent-key"
MERCHANT_KEY = "test-merchant-key"
AGENT_HEADERS = {"X-API-Key": AGENT_KEY}
MERCHANT_HEADERS = {"X-API-Key": MERCHANT_KEY}


class KeyedClient(TestClient):
    def request(self, method, url, **kwargs):
        path = str(url)
        if not path.startswith("/review/"):
            if method.upper() == "GET" or path.endswith("/review-link"):
                kwargs["headers"] = MERCHANT_HEADERS
            else:
                kwargs["headers"] = AGENT_HEADERS
        return super().request(method, url, **kwargs)
