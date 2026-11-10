# spike2_vault.py
# Spike 2: prove an AI agent can pay without a buyer popup.
#   order 1 ($18, intent AUTHORIZE) with vault attributes -> buyer approves ONCE in browser
#   -> authorize -> PayPal hands back a vault id + customer id, we save them
#   -> order 2 ($24) with payment_source.paypal.vault_id -> authorized with no buyer action
#   -> void both so the sandbox stays clean, read them back to confirm VOIDED
#
# Run it:
#   python spikes/spike2_vault.py          full flow (needs the buyer to approve once)
#   python spikes/spike2_vault.py reuse    skip order 1, reuse spikes/.vault_token.json
#
# Before running: the sandbox app needs Vault turned on (see spikes/README.md).
#
# Docs this is built from:
#   Save PayPal during purchase (Orders v2, store_in_vault, usage_type, AUTHORIZE path):
#     https://developer.paypal.com/docs/checkout/save-payment-methods/during-purchase/orders-api/paypal/
#     (now redirects to https://developer.paypal.com/api/orders-v2/save-with-purchase/paypal)
#   Use a saved payment token (payment_source.paypal.vault_id):
#     https://developer.paypal.com/api/payment-tokens/save-without-purchase/paypal#4-use-saved-payment-token
#   Orders v2 schema, source of truth for every field below (v2.36):
#     https://developer.paypal.com/api/orders/v2/schema.yaml
#     see vault_paypal_wallet_base (usage_type, customer_type, usage_pattern, description),
#     paypal_wallet_stored_credential, paypal_wallet_vault_response, and the example
#     "authorize_single_step_paypal_with_vault_id_and_stored_credentials_usage_pattern"
#     which shows create order + vault_id + AUTHORIZE coming back COMPLETED with the
#     authorization already in it (no separate /authorize call).
#   Payments v2 void + get authorization: same calls as spike 1.

import json
import os
import sys
import time
import uuid

import requests
from dotenv import load_dotenv

load_dotenv()

PAYPAL_BASE = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
client_id = os.getenv("PAYPAL_CLIENT_ID")
client_secret = os.getenv("PAYPAL_CLIENT_SECRET")

# where we stash the vault id between runs. gitignored, never commit it
VAULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".vault_token.json")


# ---- helpers copied from spike 1 on purpose, so each spike runs on its own ----


def get_token():
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
        # ask for the full object back, we need payment_source.paypal.attributes.vault
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


def get_order(token, order_id):
    response = requests.get(
        PAYPAL_BASE + "/v2/checkout/orders/" + order_id,
        headers=paypal_headers(token),
        timeout=30,
    )
    if response.status_code != 200:
        show_error("Read order", response)
    return response.json()


def wait_for_approval(token, order_id, approve_link):
    # don't trust the Enter key, ask PayPal if the buyer actually approved
    while True:
        input("Press Enter here once you've approved... ")
        status = get_order(token, order_id)["status"]
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
    return response.json()


def void_authorization(token, auth_id):
    response = requests.post(
        PAYPAL_BASE + "/v2/payments/authorizations/" + auth_id + "/void",
        headers=paypal_headers(token, idempotent=True),
        timeout=30,
    )
    # 200 with a body when Prefer is representation, 204 with nothing otherwise
    if response.status_code not in (200, 204):
        show_error("Void", response)


def check_authorization(token, auth_id):
    # read it back from PayPal so we trust their record, not ours
    response = requests.get(
        PAYPAL_BASE + "/v2/payments/authorizations/" + auth_id,
        headers=paypal_headers(token),
        timeout=30,
    )
    if response.status_code != 200:
        show_error("Read authorization", response)
    return response.json()["status"]


# ---- new for spike 2 ----


def first_authorization(order):
    # authorizations live at purchase_units[0].payments.authorizations[0]
    # returns None if the order hasn't been authorized yet
    purchase_units = order.get("purchase_units", [])
    if not purchase_units:
        return None
    authorizations = purchase_units[0].get("payments", {}).get("authorizations", [])
    if not authorizations:
        return None
    return authorizations[0]


def vault_info(order):
    # payment_source.paypal.attributes.vault -> {id, status, customer: {id}}
    paypal_source = order.get("payment_source", {}).get("paypal", {})
    return paypal_source.get("attributes", {}).get("vault")


def create_vault_order(token):
    # order 1: a normal buyer checkout, plus "save this PayPal for later"
    order_body = {
        "intent": "AUTHORIZE",
        "purchase_units": [
            {
                "reference_id": "leash-spike-2-first",
                "description": "Waxed canvas tote, olive",
                "amount": {"currency_code": "USD", "value": "18.00"},
            }
        ],
        "payment_source": {
            "paypal": {
                "attributes": {
                    "vault": {
                        # only vault once an authorization or capture succeeds
                        "store_in_vault": "ON_SUCCESS",
                        # token is for this merchant directly, not a marketplace
                        "usage_type": "MERCHANT",
                        "customer_type": "CONSUMER",
                        # on-demand, variable amount, variable timing. that's an agent
                        "usage_pattern": "IMMEDIATE",
                        # buyer sees this on the approval page and in their PayPal settings
                        "description": "Fernwood Supply Co can charge this account for "
                        "orders your shopping agent places",
                    }
                },
                "experience_context": {
                    "brand_name": "Fernwood Supply Co",
                    "user_action": "PAY_NOW",
                    "shipping_preference": "GET_FROM_FILE",
                    "return_url": "https://example.com/return",
                    "cancel_url": "https://example.com/cancel",
                },
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
        show_error("Create order 1", response)

    order = response.json()

    approve_link = None
    for link in order.get("links", []):
        if link["rel"] in ("payer-action", "approve"):
            approve_link = link["href"]
            break

    return order["id"], order["status"], approve_link


def wait_for_vault_id(token, order_id, authorize_result):
    # docs say the authorize can come back before the vault finishes saving,
    # in which case vault.status is APPROVED with no id yet. re-read the order a few times
    vault = vault_info(authorize_result)
    tries = 0
    while (not vault or not vault.get("id")) and tries < 5:
        vault_status = vault.get("status") if vault else None
        print("  vault not ready yet (" + str(vault_status) + "), checking again...")
        time.sleep(2)
        vault = vault_info(get_order(token, order_id))
        tries += 1
    return vault


def create_agent_order(token, vault_id):
    # order 2: what the agent does later. no experience_context, no return_url,
    # nobody is there to click anything
    order_body = {
        "intent": "AUTHORIZE",
        "purchase_units": [
            {
                "reference_id": "leash-spike-2-agent",
                "description": "Enamel camp mug, set of 2",
                "amount": {"currency_code": "USD", "value": "24.00"},
            }
        ],
        "payment_source": {
            "paypal": {
                "vault_id": vault_id,
                # tell PayPal the merchant started this payment, not the buyer,
                # and it's a later use of a token they already approved
                "stored_credential": {
                    "payment_initiator": "MERCHANT",
                    "usage": "SUBSEQUENT",
                    "usage_pattern": "IMMEDIATE",
                },
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
        show_error("Create order 2", response)
    return response.json()


def save_vault(vault, order_1_id, payer):
    saved = {
        "vault_id": vault["id"],
        "vault_status": vault.get("status"),
        "customer_id": vault.get("customer", {}).get("id"),
        "payer_id": payer.get("payer_id"),
        "payer_email": payer.get("email_address"),
        "first_order_id": order_1_id,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(VAULT_FILE, "w") as f:
        json.dump(saved, f, indent=2)
    return saved


def load_vault():
    if not os.path.exists(VAULT_FILE):
        print("No", VAULT_FILE, "yet. Run without 'reuse' first.")
        sys.exit(1)
    with open(VAULT_FILE) as f:
        return json.load(f)


def run_first_order(token):
    order_1_id, status, approve_link = create_vault_order(token)
    print("Order 1 created:", order_1_id, "| status:", status)

    if not approve_link:
        print("No approval link came back, paste this whole output to Claude.")
        sys.exit(1)

    # the one and only time the human has to show up
    print("\nOpen this link, log in as your SANDBOX BUYER (personal account), and approve:")
    print(approve_link)
    print("\nYou should see a line about Fernwood Supply Co saving your PayPal.")
    print("You'll land on example.com afterwards. That's expected.")
    wait_for_approval(token, order_1_id, approve_link)

    result = authorize_order(token, order_1_id)
    auth = first_authorization(result)
    print("\nOrder 1 authorized!")
    print("  order status:", result["status"])
    print("  authorization id:", auth["id"])
    print("  authorization status:", auth["status"])
    print("  expires:", auth.get("expiration_time"))

    vault = wait_for_vault_id(token, order_1_id, result)
    if not vault or not vault.get("id"):
        print("\nNo vault id came back. Vault block was:", vault)
        print("Check the app has Vault turned on, then paste this output to Claude.")
        # still clean up the $18 hold before bailing
        void_authorization(token, auth["id"])
        sys.exit(1)

    saved = save_vault(vault, order_1_id, result.get("payer", {}))
    print("\nPayPal saved the wallet!")
    print("  vault id:", saved["vault_id"])
    print("  vault status:", saved["vault_status"])
    print("  customer id:", saved["customer_id"])
    print("  written to:", VAULT_FILE)

    return saved, auth["id"]


def run_agent_order(token, vault_id):
    print("\nOrder 2: agent pays with the saved wallet, no browser...")
    order = create_agent_order(token, vault_id)
    print("Order 2 created:", order["id"], "| status:", order["status"])

    # schema example says this comes back COMPLETED with the authorization inside.
    # if this sandbox ever returns it un-authorized instead, authorize it ourselves
    auth = first_authorization(order)
    if auth is None:
        print("  no authorization on create, calling /authorize (still no buyer action)")
        order = authorize_order(token, order["id"])
        auth = first_authorization(order)

    print("\nOrder 2 authorized with zero buyer clicks!")
    print("  order status:", order["status"])
    print("  authorization id:", auth["id"])
    print("  authorization status:", auth["status"])
    print("  expires:", auth.get("expiration_time"))
    return auth["id"]


if __name__ == "__main__":
    reuse = len(sys.argv) == 2 and sys.argv[1] == "reuse"
    if len(sys.argv) > 1 and not reuse:
        print("Usage: python spikes/spike2_vault.py [reuse]")
        sys.exit(1)

    token = get_token()
    auth_ids = []

    if reuse:
        saved = load_vault()
        print("Reusing vault id", saved["vault_id"], "from", VAULT_FILE)
    else:
        saved, first_auth_id = run_first_order(token)
        auth_ids.append(first_auth_id)

    auth_ids.append(run_agent_order(token, saved["vault_id"]))

    # clean up: void every hold we made, then read each back from PayPal
    print("\nVoiding", len(auth_ids), "authorization(s) so the sandbox stays clean...")
    all_voided = True
    for auth_id in auth_ids:
        void_authorization(token, auth_id)
        status = check_authorization(token, auth_id)
        print("  " + auth_id + ":", status)
        if status != "VOIDED":
            all_voided = False

    if all_voided:
        print("\nDone. Money never moved, and the vault id is still good for next time.")
    else:
        print("\nSomething didn't void, check the statuses above.")
        sys.exit(1)
