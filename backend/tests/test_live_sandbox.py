# The one test that really talks to PayPal. Off by default, run it with:
#   pytest -m live_sandbox
# It needs PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET (sandbox) in the environment or .env.

import pytest

from backend.app.config import Settings
from backend.app.paypal_client import client_from_settings
from backend.app.verifier import check_item
from backend.tests.fakes import HOLLOWBROOK_SPEC, demo_page, spec_copy


@pytest.mark.live_sandbox
def test_a_real_sandbox_order_reads_back_matching_the_spec():
    settings = Settings()
    if not settings.paypal_client_id or not settings.paypal_client_secret:
        pytest.skip("No sandbox credentials set")

    paypal = client_from_settings(settings)
    spec = spec_copy(HOLLOWBROOK_SPEC)
    item = spec.find_item("sourdough-loaf")

    result = check_item(item, "USD", demo_page("hollowbrook-bakery").text, paypal,
                        custom_id="smoke-test")
    assert result.ok, result.reason
    assert result.paypal_order_id

    # created, never approved, never captured
    order = paypal.get_order(result.paypal_order_id)
    assert order["status"] == "CREATED"
    assert order["purchase_units"][0]["items"][0]["name"] == "Sourdough Loaf"
