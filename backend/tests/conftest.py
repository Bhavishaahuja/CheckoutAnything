import os
import tempfile

# before anything imports the app: a throwaway database file and the sandbox URL.
# a file and not :memory:, the connect run writes from its own thread
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["PAYPAL_BASE_URL"] = "https://api-m.sandbox.paypal.com"
os.environ["DEMO_MODE"] = "live"


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def review_rules_apply_to_the_test_bakery(monkeypatch):
    # most tests use the bakery as their store with flags to review. the demo's publish-it-all
    # rule for the real Hollowbrook demo store (review.PUBLISHED_ON_CONNECT) would hide that, so
    # it's off here. test_demo_publish.py turns it back on to test it
    from backend.app import review

    monkeypatch.setattr(review, "PUBLISHED_ON_CONNECT", set())
