# spike1_authorize.py
# Spike 1: prove the core money flow works in sandbox.
#   create order (intent AUTHORIZE) -> buyer approves in browser -> authorize
#   -> then either capture it or void it
#
# Run it twice:
#   python spikes/spike1_authorize.py capture
#   python spikes/spike1_authorize.py void
#
# Endpoints checked against PayPal's Orders v2 + Payments v2 OpenAPI schemas.

import os
import sys
import uuid
import requests
from dotenv import load_dotenv

load_dotenv()

PAYPAL_BASE = "https://api-m.sandbox.paypal.com"
client_id = os.getenv("PAYPAL_CLIENT_ID")
client_secret = os.getenv("PAYPAL_CLIENT_SECRET")


def get_token():
    # same client_credentials call as check_setup.py
    response = requests.post(
        PAYPAL_BASE + "/v1/oauth2/token",
        auth=(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def paypal_headers(token, idempotent=False):
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        # ask for the full object back instead of the minimal one
        "Prefer": "return=representation",
    }
    if idempotent:
        # unique per request so a retry never double-charges
        headers["PayPal-Request-Id"] = str(uuid.uuid4())
    return headers


def show_error(step, response):
    print("\n" + step + " failed:", response.status_code)
    try:
        error_body = response.json()
        print("  name:", error_body.get("name"))
        print("  message:", error_body.get("message"))
        for detail in error_body.get("details", []):
            print("  issue:", detail.get("issue"), "-", detail.get("description"))
        print("  debug_id:", error_body.get("debug_id"))
    except ValueError:
        print(response.text)
    sys.exit(1)


def create_order(token):
    # fictional store, fictional item. $42.00 so it's easy to spot in sandbox
    order_body = {
        "intent": "AUTHORIZE",
        "purchase_units": [
            {
                "reference_id": "leash-spike-1",
                "description": "Trail runner, black, size 9",
                "amount": {"currency_code": "USD", "value": "42.00"},
            }
        ],
        "payment_source": {
            "paypal": {
                "experience_context": {
                    "brand_name": "Fernwood Supply Co",
                    "user_action": "PAY_NOW",
                    "shipping_preference": "GET_FROM_FILE",
                    # these don't need to be real pages for the spike,
                    # we just need PayPal to send the buyer somewhere after approving
                    "return_url": "https://example.com/return",
                    "cancel_url": "https://example.com/cancel",
                }
            }
        },
    }

    response = requests.post(
        PAYPAL_BASE + "/v2/checkout/orders",
        headers=paypal_headers(token, idempotent=True),
        json=order_body,
        timeout=30,
    )
    if response.status_code not in (200, 201):
        show_error("Create order", response)

    order = response.json()

    # with payment_source set, PayPal returns a "payer-action" link.
    # older style returns "approve". check for both just in case.
    approve_link = None
    for link in order.get("links", []):
        if link["rel"] in ("payer-action", "approve"):
            approve_link = link["href"]
            break

    return order["id"], order["status"], approve_link


def get_order_status(token, order_id):
    # GET /v2/checkout/orders/{id} flips to APPROVED once the buyer clicks through
    response = requests.get(
        PAYPAL_BASE + "/v2/checkout/orders/" + order_id,
        headers=paypal_headers(token),
        timeout=30,
    )
    if response.status_code != 200:
        show_error("Read order", response)
    return response.json()["status"]


def wait_for_approval(token, order_id, approve_link):
    # don't trust the Enter key, ask PayPal if the buyer actually approved
    while True:
        input("Press Enter here once you've approved... ")
        status = get_order_status(token, order_id)
        if status == "APPROVED":
            print("PayPal confirms the buyer approved.")
            return
        print("\nPayPal still says:", status)
        print("Finish approving here (click the final Continue/Pay button):")
        print(approve_link)


def authorize_order(token, order_id):
    response = requests.post(
        PAYPAL_BASE + "/v2/checkout/orders/" + order_id + "/authorize",
        headers=paypal_headers(token, idempotent=True),
        json={},
        timeout=30,
    )
    if response.status_code not in (200, 201):
        show_error("Authorize", response)

    result = response.json()

    # the authorization lives at purchase_units[0].payments.authorizations[0]
    auth = result["purchase_units"][0]["payments"]["authorizations"][0]
    return auth


def capture_authorization(token, auth_id):
    # empty body = capture the full authorized amount
    response = requests.post(
        PAYPAL_BASE + "/v2/payments/authorizations/" + auth_id + "/capture",
        headers=paypal_headers(token, idempotent=True),
        json={},
        timeout=30,
    )
    if response.status_code not in (200, 201):
        show_error("Capture", response)

    capture = response.json()
    print("\nCaptured!")
    print("  capture id:", capture["id"])
    print("  status:", capture["status"])


def void_authorization(token, auth_id):
    response = requests.post(
        PAYPAL_BASE + "/v2/payments/authorizations/" + auth_id + "/void",
        headers=paypal_headers(token, idempotent=True),
        timeout=30,
    )
    # 200 with a body when Prefer is representation, 204 with nothing otherwise
    if response.status_code not in (200, 204):
        show_error("Void", response)

    print("\nVoided! Money never moved.")


def check_authorization(token, auth_id):
    # read it back from PayPal so we trust their record, not ours
    response = requests.get(
        PAYPAL_BASE + "/v2/payments/authorizations/" + auth_id,
        headers=paypal_headers(token),
        timeout=30,
    )
    if response.status_code != 200:
        show_error("Read authorization", response)

    auth = response.json()
    print("  PayPal now says this authorization is:", auth["status"])


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("capture", "void"):
        print("Usage: python spikes/spike1_authorize.py capture|void")
        sys.exit(1)

    what_to_do = sys.argv[1]
    token = get_token()

    # step 1: create the order
    order_id, status, approve_link = create_order(token)
    print("Order created:", order_id, "| status:", status)

    if not approve_link:
        print("No approval link came back, paste this whole output to Claude.")
        sys.exit(1)

    # step 2: human approves as the sandbox buyer
    print("\nOpen this link, log in as your SANDBOX BUYER (personal account), and approve:")
    print(approve_link)
    print("\nYou'll land on example.com afterwards. That's expected.")
    wait_for_approval(token, order_id, approve_link)

    # step 3: authorize (puts the hold on the buyer's funds)
    auth = authorize_order(token, order_id)
    auth_id = auth["id"]
    print("\nAuthorized!")
    print("  authorization id:", auth_id)
    print("  status:", auth["status"])
    print("  expires:", auth.get("expiration_time"))

    # step 4: capture or void
    if what_to_do == "capture":
        capture_authorization(token, auth_id)
    else:
        void_authorization(token, auth_id)

    check_authorization(token, auth_id)
