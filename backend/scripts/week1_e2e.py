# week1_e2e.py
# Week 1 end to end, against a running Leash API (local or Render):
#   1. create a mandate (Claude parses it)
#   2. order A with the saved vault id -> authorized with no buyer action -> capture
#   3. order B with the saved vault id -> authorized -> void
#   4. read both back from PayPal: A's authorization CAPTURED and its capture COMPLETED,
#      B's authorization VOIDED
#
# Run from the repo root:
#   python backend/scripts/week1_e2e.py                                   localhost:8000
#   python backend/scripts/week1_e2e.py https://leash-api.onrender.com    Render
#
# Needs spikes/.vault_token.json (run spikes/spike2_vault.py once) and the PayPal keys in
# your local .env, for the read-back. The API side needs its own keys (Render env vars).
# Money never really moves: it's sandbox, and order B is voided.

import json
import os
import sys
import time

# make "backend.app" importable when run as a script
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

import requests  # noqa: E402

from backend.app.config import get_settings  # noqa: E402
from backend.app.paypal_client import client_from_settings  # noqa: E402

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
VAULT_FILE = os.path.join(REPO_ROOT, "spikes", ".vault_token.json")

MANDATE = {
    "buyer_label": "week1-e2e",
    "request_text": "Get me black trail runners, women's size 9, and a pair of hiking socks, "
    "under $120 all in, from Fernwood Supply Co, sometime this week.",
    "merchant": "Fernwood Supply Co",
}

ORDER_A_ITEMS = [
    {"name": "Trail runner", "color": "black", "size": "W9", "quantity": 1,
     "unit_price": "89.00"},
    {"name": "Wool hiking socks", "quantity": 1, "unit_price": "14.00"},
]
ORDER_B_ITEMS = [
    {"name": "Wool hiking socks", "quantity": 2, "unit_price": "14.00"},
]

problems = []


def check(label, actual, expected):
    if actual == expected:
        print("  ok   " + label + ": " + str(actual))
    else:
        print("  FAIL " + label + ": got " + str(actual) + ", expected " + str(expected))
        problems.append(label)


def call(method, base_url, path, body=None):
    response = requests.request(method, base_url + path, json=body, timeout=120)
    if response.status_code >= 400:
        print("  " + method + " " + path + " failed:", response.status_code, response.text)
        sys.exit(1)
    return response.json()


def wait_for_health(base_url):
    # a free Render service sleeps after 15 minutes idle, waking it takes about a minute
    print("Checking " + base_url + "/health ...")
    for attempt in range(1, 19):
        try:
            response = requests.get(base_url + "/health", timeout=30)
            if response.status_code == 200:
                print("  API is up:", response.json())
                return
            print("  attempt " + str(attempt) + ": " + str(response.status_code))
        except requests.RequestException as error:
            print("  attempt " + str(attempt) + ": " + type(error).__name__)
        time.sleep(10)
    print("API never came up.")
    sys.exit(1)


def place_order(base_url, mandate_id, vault_id, items, label):
    order = call("POST", base_url, "/orders", {
        "mandate_id": mandate_id,
        "vault_id": vault_id,
        "items": items,
        "shipping": "5.00",
    })
    print("\n" + label + ": order " + str(order["id"]) + ", total $" + order["total"])
    print("  paypal order:", order["paypal_order_id"])
    print("  authorization:", order["authorization_id"])
    print("  expires:", order["authorization_expires_at"])
    check(label + " status after create", order["status"], "authorized")
    # with a vault id there's nobody to click anything
    check(label + " needs buyer action", order.get("payer_action_url"), None)
    return order


def main():
    base_url = DEFAULT_BASE_URL
    if len(sys.argv) == 2:
        base_url = sys.argv[1]
    elif len(sys.argv) > 2:
        print("Usage: python backend/scripts/week1_e2e.py [base_url]")
        sys.exit(1)
    base_url = base_url.rstrip("/")

    if not os.path.exists(VAULT_FILE):
        print("No " + VAULT_FILE + ". Run python spikes/spike2_vault.py once first.")
        sys.exit(1)
    with open(VAULT_FILE) as f:
        vault_id = json.load(f)["vault_id"]

    wait_for_health(base_url)

    # 1. mandate
    mandate = call("POST", base_url, "/mandates", MANDATE)
    print("\nMandate " + str(mandate["id"]) + " created")
    rules = mandate["rules"]
    print("  item:", rules.get("item"), "| max_price:", mandate["max_price"],
          "| merchant:", mandate["merchant"], "| expires:", mandate["expires_at"])

    # 2. order A: authorize (no buyer action) then capture
    order_a = place_order(base_url, mandate["id"], vault_id, ORDER_A_ITEMS, "Order A")
    order_a = call("POST", base_url, "/orders/" + str(order_a["id"]) + "/capture")
    print("  capture:", order_a["capture_id"])
    check("Order A status after capture", order_a["status"], "captured")

    # 3. order B: authorize then void
    order_b = place_order(base_url, mandate["id"], vault_id, ORDER_B_ITEMS, "Order B")
    order_b = call("POST", base_url, "/orders/" + str(order_b["id"]) + "/void")
    check("Order B status after void", order_b["status"], "voided")

    # 4. trust PayPal's record, not ours
    print("\nReading back from PayPal...")
    paypal = client_from_settings(get_settings())
    auth_a = paypal.get_authorization(order_a["authorization_id"])
    check("PayPal: order A authorization", auth_a["status"], "CAPTURED")
    capture_a = paypal.get_capture(order_a["capture_id"])
    check("PayPal: order A capture", capture_a["status"], "COMPLETED")
    auth_b = paypal.get_authorization(order_b["authorization_id"])
    check("PayPal: order B authorization", auth_b["status"], "VOIDED")

    # and the API's own read side agrees
    detail = call("GET", base_url, "/orders/" + str(order_a["id"]))
    check("GET order A mandate id", detail["mandate"]["id"], mandate["id"])

    print()
    if problems:
        print("Week 1 e2e FAILED: " + ", ".join(problems))
        sys.exit(1)
    print("Week 1 e2e passed: mandate, vault authorize, capture, void, all confirmed by PayPal.")


if __name__ == "__main__":
    main()
