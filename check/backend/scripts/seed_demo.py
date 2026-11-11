# seed_demo.py
# Resets the demo on a running Check API and puts the seed back, or just prints where it stands.
# The work happens on the API (POST /demo/reset, see backend/app/demo.py and demo_seed.py), so the
# script only needs the merchant key. It's the same reset as the dashboard's Reset demo button.
#
# Run from the check folder, in cmd:
#   .venv\Scripts\python.exe backend\scripts\seed_demo.py --reset    reset + reseed, then counts
#   .venv\Scripts\python.exe backend\scripts\seed_demo.py            just the counts
# against Render:
#   .venv\Scripts\python.exe backend\scripts\seed_demo.py --reset --base-url URL
# or set LEASH_API_URL once in the cmd window instead of passing --base-url every time:
#   set LEASH_API_URL=https://leash-api-q3rw.onrender.com
#
# Needs MERCHANT_API_KEY in .env (or set in the cmd window), matching the API's. The API itself
# needs the two seed agents in AGENT_API_KEYS and STORE_NAMING_AGENTS, and DEMO_VAULT_ID. It says
# which one is missing if it can't seed, before it touches anything.
#
# Exits non-zero if the reset failed or any seed order didn't land where it should.

import argparse
import os
import sys
import time

# make "backend.app" importable when run as a script
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

import requests  # noqa: E402

from backend.app.config import get_settings  # noqa: E402

# --base-url wins, then LEASH_API_URL, then the local API. read straight from the environment on
# purpose, not .env: a line left in .env shouldn't quietly point a local run at Render
DEFAULT_BASE_URL = os.environ.get("LEASH_API_URL", "").strip() or "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 60
# how long to wait for the reset before giving up on it. it keeps going on the API either way
RESET_WAIT_SECONDS = 15 * 60
POLL_SECONDS = 3

UNKNOWN_AGENT = "Unknown agent"
HELD_STATES = ("needs_review", "approved", "rejected")


class ApiError(Exception):
    pass


class CheckApi:
    # http is a requests session, or the tests' TestClient, which takes the same calls

    def __init__(self, http, base_url, merchant_key):
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.merchant = {"X-API-Key": merchant_key}

    def call(self, method, path, ok=(200, 201, 202)):
        response = self.http.request(
            method, self.base_url + path, headers=self.merchant, timeout=TIMEOUT_SECONDS
        )
        if response.status_code not in ok:
            raise ApiError(
                method + " " + path + " returned " + str(response.status_code)
                + ": " + response.text[:400]
            )
        return response.json()


def run_reset(api, wait_seconds=RESET_WAIT_SECONDS, poll_seconds=POLL_SECONDS, sleep=time.sleep):
    # starts the reset and waits for it, printing each step once. returns the final status
    status = api.call("POST", "/demo/reset")
    started = time.monotonic()
    last_step = None
    while status["state"] == "running":
        if status.get("step") and status["step"] != last_step:
            last_step = status["step"]
            print("  " + last_step, flush=True)
        if time.monotonic() - started > wait_seconds:
            raise ApiError("Still running after " + str(wait_seconds) + "s. It carries on on the "
                           "API, run this without --reset in a bit to see where it got to")
        sleep(poll_seconds)
        status = api.call("GET", "/demo/reset")
    return status


def count_orders(orders):
    # the numbers the dashboard should show, worked out from GET /orders
    counts = {
        "orders": 0, "captured": 0, "auto_captured": 0, "held": 0, "approved": 0,
        "rejected": 0, "pending": 0, "voided": 0, "by_agent": {}, "by_store": {},
    }
    for order in orders:
        counts["orders"] += 1
        status = order["status"]
        review_state = order["review_state"]
        if status == "captured":
            counts["captured"] += 1
        if status == "voided":
            counts["voided"] += 1
        if review_state == "auto_approved":
            counts["auto_captured"] += 1
        if review_state in HELD_STATES:
            counts["held"] += 1
        if review_state == "approved":
            counts["approved"] += 1
        if review_state == "rejected":
            counts["rejected"] += 1
        if review_state == "needs_review" and status == "authorized":
            counts["pending"] += 1

        agent = order.get("agent_name") or UNKNOWN_AGENT
        if agent not in counts["by_agent"]:
            counts["by_agent"][agent] = {"orders": 0, "captured": 0, "held": 0, "voided": 0}
        counts["by_agent"][agent]["orders"] += 1
        if status == "captured":
            counts["by_agent"][agent]["captured"] += 1
        if review_state in HELD_STATES:
            counts["by_agent"][agent]["held"] += 1
        if status == "voided":
            counts["by_agent"][agent]["voided"] += 1

        store = order.get("merchant") or "(Check's own store)"
        counts["by_store"][store] = counts["by_store"].get(store, 0) + 1
    return counts


def cell(value, width):
    text = "-" if value is None else str(value)
    return text.ljust(width)


def print_seed_orders(status):
    print()
    print(cell("SEED ORDER", 36) + cell("AGENT", 19) + cell("STORE", 26) + cell("ORDER", 7)
          + cell("STATUS", 11) + "REVIEW")
    print("-" * 115)
    for order in status["orders"]:
        print(cell(order["name"], 36) + cell(order["agent_name"], 19) + cell(order["store"], 26)
              + cell(order["order_id"], 7) + cell(order["status"], 11)
              + str(order["review_state"]))
    for order in status["orders"]:
        if order["problem"]:
            print("WRONG: " + order["name"] + ": " + order["problem"])


def print_counts(counts, stats):
    print()
    print("Orders " + str(counts["orders"]) + ": captured " + str(counts["captured"])
          + " (auto " + str(counts["auto_captured"]) + ", approved " + str(counts["approved"])
          + "), held " + str(counts["held"]) + ", voided " + str(counts["voided"])
          + ", waiting on a human " + str(counts["pending"]))
    for agent in sorted(counts["by_agent"]):
        row = counts["by_agent"][agent]
        print("  " + agent + ": " + str(row["orders"]) + " orders, " + str(row["captured"])
              + " captured, " + str(row["held"]) + " held, " + str(row["voided"]) + " voided")
    for store in sorted(counts["by_store"]):
        print("  at " + store + ": " + str(counts["by_store"][store]))
    print("Rubber-stamp watch: " + str(stats["fast_streak"]) + " of 3, sharp mode "
          + ("ON" if stats["rubber_stamp_active"] else "off"))


def main():
    # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Reset and reseed the Check demo")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--reset", action="store_true",
                        help="void open holds, delete the demo orders and place the seed again")
    args = parser.parse_args()

    merchant_key = get_settings().merchant_api_key
    if not merchant_key:
        print("MERCHANT_API_KEY has to be in .env (or set in this window), matching the API's.")
        return 1

    api = CheckApi(requests.Session(), args.base_url, merchant_key)
    problems = 0
    try:
        if args.reset:
            # say where first: this voids holds and deletes rows, it matters which API it hits
            print("Resetting " + api.base_url + "...")
            began = time.monotonic()
            status = run_reset(api)
            took = int(time.monotonic() - began)
            if status["state"] != "done":
                print("Reset failed: " + str(status.get("error")))
                return 1
            print("Voided " + str(status["voided_holds"]) + " holds, deleted "
                  + str(status["deleted_orders"]) + " orders and "
                  + str(status["deleted_mandates"]) + " mandates and "
                  + str(status.get("deleted_disputes", 0)) + " disputes, kept orders "
                  + str(status["protected_order_ids"]) + ". Took " + str(took) + "s.")
            print_seed_orders(status)
            for order in status["orders"]:
                if order["problem"]:
                    problems += 1

        orders = api.call("GET", "/orders?limit=200")
        stats = api.call("GET", "/stats")
    except (ApiError, requests.RequestException) as error:
        print("Failed: " + str(error))
        return 1

    print_counts(count_orders(orders), stats)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
