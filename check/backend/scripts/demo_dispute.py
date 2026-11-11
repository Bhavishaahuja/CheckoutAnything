# demo_dispute.py
# Opens the demo's sandbox dispute and walks it to WAITING_FOR_SELLER_RESPONSE, so Check can file
# evidence on it. Sandbox only. The full by-hand version is docs/demo-dispute.md in the repo root.
#
# Run from the check folder, in cmd:
#   .venv\Scripts\python.exe backend\scripts\demo_dispute.py open <buyer transaction id> 146.00
#   .venv\Scripts\python.exe backend\scripts\demo_dispute.py show PP-R-XXX-12345678
#   .venv\Scripts\python.exe backend\scripts\demo_dispute.py advance PP-R-XXX-12345678
#   .venv\Scripts\python.exe backend\scripts\demo_dispute.py wait PP-R-XXX-12345678
#
#   open      opens an "item not as described" dispute as the sandbox buyer
#   show      stage, status, what PayPal wants from the seller, and whether Check can file now
#   advance   one step toward ready: escalate an inquiry to a claim, or on a claim that's
#             UNDER_REVIEW, the sandbox-only require-evidence call with SELLER_EVIDENCE
#   wait      runs advance and show every 30 seconds until Check can file, up to 15 minutes
#
# Needs PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET and SANDBOX_BUYER_EMAIL in .env (the merchant's
# sandbox app, and the sandbox buyer who paid).
#
# The buyer transaction id is the buyer's own id for the payment. It isn't our capture id: copy
# it from the buyer's sandbox account, Activity, click the payment, "Transaction ID".
#
# Every call here is from PayPal's docs, not guessed:
#   create (sandbox only, buyer side, PayPal-Auth-Assertion + multipart "input"):
#     https://developer.paypal.com/disputes/test-go-live  ("Create dispute")
#     the API reference lists create as limited release, so a 403 here means do it by hand
#   escalate (stage must be INQUIRY):
#     https://developer.paypal.com/api/customer-disputes/v1/disputes-escalate
#   require-evidence (sandbox only, status must be UNDER_REVIEW with a require-evidence link,
#   action SELLER_EVIDENCE moves it to WAITING_FOR_SELLER_RESPONSE):
#     https://developer.paypal.com/api/customer-disputes/v1/disputes-require-evidence

import argparse
import base64
import json
import os
import sys
import time
import uuid

import requests
from dotenv import load_dotenv

PAYPAL_BASE = "https://api-m.sandbox.paypal.com"
NOT_AS_DESCRIBED = "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"
WAITING_FOR_SELLER = "WAITING_FOR_SELLER_RESPONSE"
# same two spellings Check accepts, see PROVIDE_EVIDENCE_RELS in backend/app/disputes.py
PROVIDE_EVIDENCE_RELS = ["provide-evidence", "provide_evidence"]
REQUIRE_EVIDENCE_RELS = ["require-evidence", "require_evidence"]
ESCALATE_RELS = ["escalate"]
# what Check can file without making anything up, see NEEDS_INFO_WE_DONT_HAVE in disputes.py
TYPES_CHECK_CAN_SEND = ["OTHER"]

WAIT_EVERY_SECONDS = 30
WAIT_AT_MOST_SECONDS = 15 * 60


def auth_assertion(client_id, buyer_email):
    # the unsigned JWT PayPal's sandbox create call takes: {"alg": "none"} and a payload naming
    # our app (iss) and the buyer we're acting as. no signature, so it ends with a bare "."
    def part(data):
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    header = part({"alg": "none", "typ": "JWT"})
    payload = part({"iss": client_id, "email": buyer_email})
    return header + "." + payload + "."


def create_dispute_input(buyer_transaction_id, amount, reason=NOT_AS_DESCRIBED):
    # the "input" part of the create call, field for field from the docs' sample
    return {
        "disputed_transactions": [{"buyer_transaction_id": buyer_transaction_id}],
        "reason": reason,
        "dispute_amount": {"currency_code": "USD", "value": str(amount)},
        "extensions": {
            "merchant_contacted": True,
            "merchant_contacted_outcome": "NO_RESPONSE",
            "merchandize_dispute_properties": {"issue_type": "PRODUCT"},
        },
    }


def link_rels(details):
    rels = []
    for link in details.get("links") or []:
        rels.append(link.get("rel"))
    return rels


def has_any(rels, wanted):
    for rel in wanted:
        if rel in rels:
            return True
    return False


def requested_types(details):
    types = []
    for evidence in details.get("evidences") or []:
        if evidence.get("source") == "REQUESTED_FROM_SELLER" and evidence.get("evidence_type"):
            types.append(evidence["evidence_type"])
    return types


def readiness(details):
    # (ready, what to do). ready means Check's "Submit evidence" will go through
    status = details.get("status")
    rels = link_rels(details)
    if status == WAITING_FOR_SELLER and has_any(rels, PROVIDE_EVIDENCE_RELS):
        wanted = requested_types(details)
        if not wanted:
            return True, "Ready. PayPal asked for nothing specific, Check files it as OTHER"
        for evidence_type in wanted:
            if evidence_type in TYPES_CHECK_CAN_SEND:
                return True, "Ready. PayPal asked for " + ", ".join(wanted)
        return False, (
            "PayPal only asked for " + ", ".join(wanted) + ", which Check won't send. "
            "See \"If PayPal asks for evidence Check won't send\" in docs/demo-dispute.md"
        )
    if status in ("RESOLVED", "OTHER"):
        return False, "This dispute is closed. Open a new one on a new order"
    return False, "Not ready yet: " + str(status) + ". Run advance, or wait"


def next_step(details):
    # which move gets this dispute closer to WAITING_FOR_SELLER_RESPONSE, or None
    rels = link_rels(details)
    status = details.get("status")
    if status == WAITING_FOR_SELLER:
        return None
    if status == "UNDER_REVIEW" and has_any(rels, REQUIRE_EVIDENCE_RELS):
        return "require-evidence"
    if details.get("dispute_life_cycle_stage") == "INQUIRY" and has_any(rels, ESCALATE_RELS):
        return "escalate"
    return None


class SandboxPayPal:
    def __init__(self, client_id, client_secret, buyer_email=""):
        self.client_id = client_id
        self.client_secret = client_secret
        self.buyer_email = buyer_email
        self.token = None

    def get_token(self):
        if self.token is None:
            response = requests.post(
                PAYPAL_BASE + "/v1/oauth2/token",
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                timeout=30,
            )
            response.raise_for_status()
            self.token = response.json()["access_token"]
        return self.token

    def headers(self, content_type="application/json"):
        headers = {
            "Authorization": "Bearer " + self.get_token(),
            "PayPal-Request-Id": str(uuid.uuid4()),
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def check(self, response, what):
        if response.status_code >= 400:
            print(what + " failed: " + str(response.status_code) + " " + response.text[:600])
            if response.status_code in (401, 403) and what == "Open dispute":
                print("PayPal keeps creating disputes by API for some apps (limited release). "
                      "Open it by hand instead, see docs/demo-dispute.md")
            sys.exit(1)
        if not response.content:
            return {}
        return response.json()

    def create(self, buyer_transaction_id, amount):
        # multipart, no Content-Type of our own: requests has to add the boundary
        headers = self.headers(content_type=None)
        headers["PayPal-Auth-Assertion"] = auth_assertion(self.client_id, self.buyer_email)
        body = json.dumps(create_dispute_input(buyer_transaction_id, amount))
        response = requests.post(
            PAYPAL_BASE + "/v1/customer/disputes", headers=headers,
            files={"input": (None, body, "application/json")}, timeout=60,
        )
        return self.check(response, "Open dispute")

    def show(self, dispute_id):
        response = requests.get(
            PAYPAL_BASE + "/v1/customer/disputes/" + dispute_id, headers=self.headers(),
            timeout=30,
        )
        return self.check(response, "Show dispute")

    def escalate(self, dispute_id):
        response = requests.post(
            PAYPAL_BASE + "/v1/customer/disputes/" + dispute_id + "/escalate",
            headers=self.headers(), json={"note": "Escalating to a claim for review."},
            timeout=30,
        )
        return self.check(response, "Escalate")

    def require_seller_evidence(self, dispute_id):
        response = requests.post(
            PAYPAL_BASE + "/v1/customer/disputes/" + dispute_id + "/require-evidence",
            headers=self.headers(), json={"action": "SELLER_EVIDENCE"}, timeout=30,
        )
        return self.check(response, "Require evidence")


def print_details(details):
    print("Dispute " + str(details.get("dispute_id")) + ": "
          + str(details.get("reason")) + ", stage " + str(details.get("dispute_life_cycle_stage"))
          + ", status " + str(details.get("status")))
    if details.get("seller_response_due_date"):
        print("  Seller must answer by " + str(details["seller_response_due_date"]))
    wanted = requested_types(details)
    print("  PayPal asks the seller for: " + (", ".join(wanted) if wanted else "nothing specific"))
    allowed = []
    for rel in link_rels(details):
        if rel != "self":
            allowed.append(str(rel))
    print("  Allowed now: " + (", ".join(allowed) if allowed else "nothing"))
    print("  " + readiness(details)[1])


def advance(paypal, dispute_id):
    details = paypal.show(dispute_id)
    step = next_step(details)
    if step == "escalate":
        print("Escalating the inquiry to a claim...")
        paypal.escalate(dispute_id)
    elif step == "require-evidence":
        print("Asking the sandbox for seller evidence (require-evidence SELLER_EVIDENCE)...")
        paypal.require_seller_evidence(dispute_id)
    else:
        print("Nothing to move right now")
    return step


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open and advance the demo's sandbox dispute")
    commands = parser.add_subparsers(dest="command", required=True)
    open_command = commands.add_parser("open")
    open_command.add_argument("buyer_transaction_id")
    open_command.add_argument("amount", help="the payment's total, e.g. 146.00")
    for name in ("show", "advance", "wait"):
        commands.add_parser(name).add_argument("dispute_id")
    args = parser.parse_args(argv)

    load_dotenv()
    if os.getenv("PAYPAL_BASE_URL", PAYPAL_BASE) != PAYPAL_BASE:
        print("PAYPAL_BASE_URL isn't the sandbox. This script only ever runs against the sandbox")
        return 1
    paypal = SandboxPayPal(
        os.getenv("PAYPAL_CLIENT_ID", ""), os.getenv("PAYPAL_CLIENT_SECRET", ""),
        os.getenv("SANDBOX_BUYER_EMAIL", ""),
    )

    if args.command == "open":
        if not paypal.buyer_email:
            print("Set SANDBOX_BUYER_EMAIL in .env to the sandbox buyer who paid")
            return 1
        created = paypal.create(args.buyer_transaction_id, args.amount)
        print("Opened. PayPal says:")
        for link in created.get("links") or []:
            print("  " + str(link.get("rel")) + ": " + str(link.get("href")))
        print("The dispute id is the last part of the self link. Next: show, then advance")
        return 0

    if args.command == "show":
        print_details(paypal.show(args.dispute_id))
        return 0

    if args.command == "advance":
        advance(paypal, args.dispute_id)
        time.sleep(3)
        print_details(paypal.show(args.dispute_id))
        return 0

    waited = 0
    while True:
        details = paypal.show(args.dispute_id)
        ready, message = readiness(details)
        print("[" + str(waited) + "s] " + str(details.get("dispute_life_cycle_stage")) + " / "
              + str(details.get("status")) + ". " + message)
        if ready:
            return 0
        if waited >= WAIT_AT_MOST_SECONDS:
            print("Still not ready after 15 minutes. Check it in the sandbox Resolution Center")
            return 1
        if next_step(details):
            advance(paypal, args.dispute_id)
        time.sleep(WAIT_EVERY_SECONDS)
        waited += WAIT_EVERY_SECONDS


if __name__ == "__main__":
    sys.exit(main())
