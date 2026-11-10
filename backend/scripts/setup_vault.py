# One-time setup: save a sandbox buyer's PayPal wallet so the buy endpoint can pay with it
# later with nobody there to click. Prints the vault id to put in BUYER_VAULT_ID.
#
#   python backend/scripts/setup_vault.py
#
# It creates a $1.00 sandbox order that asks to save the wallet, you approve it ONCE in the
# browser as your sandbox buyer (personal account), it captures, and PayPal hands back the id.
# The sandbox app needs Vault turned on first.
#
# Shapes are from https://developer.paypal.com/api/orders-v2/save-with-purchase/paypal and
# the Orders v2 schema (vault_paypal_wallet_base). Adapted from the Leash repo's spike 2.

import sys
import time
from pathlib import Path

# so "python backend/scripts/setup_vault.py" works from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.config import get_settings  # noqa: E402
from backend.app.paypal_client import (  # noqa: E402
    PAYPAL_FAILURES,
    client_from_settings,
    describe_failure,
)


def vault_info(order):
    # payment_source.paypal.attributes.vault -> {id, status, customer: {id}}
    paypal_source = (order.get("payment_source") or {}).get("paypal") or {}
    return (paypal_source.get("attributes") or {}).get("vault")


def approve_link(order):
    # the schema says payer-action, one doc sample says approve. take either
    for wanted in ("payer-action", "approve"):
        for link in order.get("links") or []:
            if link.get("rel") == wanted:
                return link.get("href")
    return None


def main():
    settings = get_settings()
    paypal = client_from_settings(settings)

    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "description": "Checkout Anything wallet setup",
            "amount": {"currency_code": "USD", "value": "1.00"},
        }],
        "payment_source": {
            "paypal": {
                "attributes": {
                    "vault": {
                        # only saved once the capture succeeds
                        "store_in_vault": "ON_SUCCESS",
                        "usage_type": "MERCHANT",
                        "customer_type": "CONSUMER",
                        # on demand, any amount, any time. that's a shopping agent
                        "usage_pattern": "IMMEDIATE",
                        "description": "Checkout Anything demo: orders placed by your "
                                       "shopping agent",
                    }
                },
                "experience_context": {
                    "brand_name": "Checkout Anything",
                    "user_action": "PAY_NOW",
                    "shipping_preference": "NO_SHIPPING",
                    "return_url": "https://example.com/return",
                    "cancel_url": "https://example.com/cancel",
                },
            }
        },
    }

    try:
        order = paypal.create_order(body)
    except PAYPAL_FAILURES as error:
        print("Couldn't create the setup order.", describe_failure(error))
        return 1

    link = approve_link(order)
    if not link:
        print("PayPal sent no approval link. Status was", order.get("status"))
        return 1

    print("Open this link, log in as your SANDBOX BUYER (personal account) and approve:")
    print()
    print("  " + link)
    print()
    print("You'll land on example.com afterwards. That's expected.")

    # don't trust the Enter key, ask PayPal whether the buyer really approved
    while True:
        input("Press Enter here once you've approved... ")
        try:
            status = paypal.get_order(order["id"]).get("status")
        except PAYPAL_FAILURES as error:
            print(describe_failure(error))
            continue
        if status == "APPROVED":
            break
        print("PayPal still says", status + ". Finish approving at the link above.")

    try:
        captured = paypal.capture_order(order["id"])
    except PAYPAL_FAILURES as error:
        print("Couldn't capture the setup order.", describe_failure(error))
        return 1

    # the capture can come back before the wallet finishes saving (vault status APPROVED,
    # no id yet). re-read the order a few times
    vault = vault_info(captured)
    tries = 0
    while (not vault or not vault.get("id")) and tries < 5:
        time.sleep(2)
        try:
            vault = vault_info(paypal.get_order(order["id"]))
        except PAYPAL_FAILURES:
            pass
        tries += 1

    if not vault or not vault.get("id"):
        print("PayPal captured the $1.00 but returned no vault id. Vault block:", vault)
        print("Check that the sandbox app has Vault turned on, then run this again.")
        return 1

    print()
    print("Saved. Put this in .env (and in the Render dashboard):")
    print()
    print("  BUYER_VAULT_ID=" + vault["id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
