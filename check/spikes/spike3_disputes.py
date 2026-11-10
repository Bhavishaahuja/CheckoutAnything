# spike3_disputes.py
# Spike 3: can the merchant file evidence on a sandbox dispute through the Disputes API?
# That's how Leash will hand PayPal the mandate + approval record when a buyer disputes.
#
# Run it:
#   python spikes/spike3_disputes.py list                  open disputes for our merchant
#   python spikes/spike3_disputes.py show <dispute_id>     reason, status, amount, due date
#   python spikes/spike3_disputes.py evidence <dispute_id> file a note + a small PDF, read back
#   python spikes/spike3_disputes.py evidence <dispute_id> --type OTHER   force an evidence type
#
# By default "evidence" sends the type PayPal asked for (evidences[] with source
# REQUESTED_FROM_SELLER). PayPal rejects anything else with EVIDENCE_TYPE_IS_NOT_ALLOWED,
# we found that out the hard way sending OTHER on an INR case.
#
# Before running: the sandbox app needs Customer disputes on, and you need a dispute to
# look at. Steps for both are in spikes/README.md under "Spike 3 findings".
#
# Docs this is built from:
#   Disputes v1 API reference:
#     https://developer.paypal.com/api/customer-disputes/v1
#   Disputes v1 schema, source of truth for paths and fields:
#     https://developer.paypal.com/api/customer-disputes/v1/schema.yaml
#     (provide-evidence: only when status is WAITING_FOR_SELLER_RESPONSE, and only via
#     the provide_evidence HATEOAS link from show dispute details. no link, no evidence)
#   Use Disputes API (list, show, provide-evidence sample with -F 'input=...' + file part,
#   stage/status table of allowed actions):
#     https://developer.paypal.com/platforms/disputes/handle-disputes/use-disputes-api
#   Sandbox testing (buyer creates an INR case, evidence type OTHER with notes + documents):
#     https://developer.paypal.com/disputes/test-go-live
#   App setup (Features > Add-on services > Customer disputes):
#     https://developer.paypal.com/disputes/set-up
#   File rules (.jpg .jpeg .gif .png .pdf only, under 10 MB each, 50 MB per call):
#     https://developer.paypal.com/disputes/supported-file-sizes-types
#   Which evidence types each dispute reason accepts (INR: PROOF_OF_FULFILLMENT or
#   PROOF_OF_REFUND only, no OTHER. UNAUTHORISED: fulfillment, refund, or OTHER):
#     https://developer.paypal.com/platforms/disputes/reference/dispute-reasons
#   Schema bits used for PROOF_OF_FULFILLMENT (same schema.yaml as above):
#     evidence_info.tracking_info[] requires carrier_name + tracking_number.
#     carrier_name is an enum of real carriers, so we send OTHER plus carrier_name_other
#     (free text, mandatory when carrier_name is OTHER) to keep the carrier fictional

import json
import os
import sys
import uuid

import requests
from dotenv import load_dotenv

load_dotenv()

PAYPAL_BASE = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
client_id = os.getenv("PAYPAL_CLIENT_ID")
client_secret = os.getenv("PAYPAL_CLIENT_SECRET")


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
        "Prefer": "return=representation",
    }
    if idempotent:
        # unique per request so a retry never double-submits
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


# ---- disputes ----


def format_money(money):
    if not money:
        return "?"
    return money.get("value", "?") + " " + money.get("currency_code", "")


def link_for(dispute, rel):
    # PayPal tells us what we're allowed to do via HATEOAS links
    for link in dispute.get("links", []):
        if link.get("rel") == rel:
            return link["href"]
    return None


def list_disputes(token):
    # GET /v1/customer/disputes gives a summary per dispute. follow the "next" link
    # to get every page. we filter out RESOLVED ourselves instead of trusting a query param
    url = PAYPAL_BASE + "/v1/customer/disputes?page_size=50"
    all_disputes = []
    pages_read = 0
    while url and pages_read < 10:
        response = requests.get(url, headers=paypal_headers(token), timeout=30)
        if response.status_code != 200:
            show_error("List disputes", response)
        page = response.json()
        for dispute in page.get("items", []):
            all_disputes.append(dispute)
        url = None
        for link in page.get("links", []):
            if link.get("rel") == "next":
                url = link["href"]
        pages_read += 1

    open_disputes = []
    for dispute in all_disputes:
        if dispute.get("status") != "RESOLVED":
            open_disputes.append(dispute)

    print("Found", len(all_disputes), "dispute(s),", len(open_disputes), "not resolved.\n")
    for dispute in open_disputes:
        print(dispute.get("dispute_id"))
        print("  reason:", dispute.get("reason"))
        print("  status:", dispute.get("status"))
        print("  stage:", dispute.get("dispute_life_cycle_stage"))
        print("  amount:", format_money(dispute.get("dispute_amount")))
        print("  created:", dispute.get("create_time"))


def get_dispute(token, dispute_id):
    response = requests.get(
        PAYPAL_BASE + "/v1/customer/disputes/" + dispute_id,
        headers=paypal_headers(token),
        timeout=30,
    )
    if response.status_code != 200:
        show_error("Show dispute", response)
    return response.json()


def print_dispute(dispute):
    print("Dispute", dispute.get("dispute_id"))
    print("  reason:", dispute.get("reason"))
    print("  status:", dispute.get("status"))
    print("  dispute_state:", dispute.get("dispute_state"))
    print("  stage:", dispute.get("dispute_life_cycle_stage"))
    print("  amount:", format_money(dispute.get("dispute_amount")))
    print("  seller response due:", dispute.get("seller_response_due_date"))

    # seller_transaction_id should be the capture id we got back in spike 1
    for transaction in dispute.get("disputed_transactions", []):
        print("  disputed transaction (seller side):", transaction.get("seller_transaction_id"))
        print("  disputed transaction (buyer side):", transaction.get("buyer_transaction_id"))

    print("  evidence on file / requested:")
    evidences = dispute.get("evidences", [])
    if not evidences:
        print("    none")
    for evidence in evidences:
        document_names = []
        for document in evidence.get("documents", []):
            document_names.append(document.get("name"))
        print(
            "    -",
            evidence.get("evidence_type"),
            "| source:",
            evidence.get("source"),
            "| notes:",
            evidence.get("notes"),
            "| documents:",
            document_names,
        )

    actions = []
    for link in dispute.get("links", []):
        if link.get("rel") != "self":
            actions.append(link.get("rel"))
    print("  actions PayPal allows right now:", actions)


def pdf_escape(text):
    # backslash and parens are special inside a PDF string
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_tiny_pdf(lines):
    # hand-rolled one page PDF so we don't pull in a PDF library for a spike.
    # PayPal only takes jpg/gif/png/pdf, so a .txt file wouldn't work
    text_ops = "BT /F1 11 Tf 72 720 Td 16 TL\n"
    for line in lines:
        text_ops += "(" + pdf_escape(line) + ") Tj T*\n"
    text_ops += "ET"
    stream = text_ops.encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    pdf = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += str(number).encode() + b" 0 obj\n" + body + b"\nendobj\n"

    # the xref table is byte offsets of each object, 20 bytes per entry
    xref_start = len(pdf)
    pdf += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    pdf += b"0000000000 65535 f \n"
    for offset in offsets:
        pdf += ("%010d 00000 n \n" % offset).encode()
    pdf += b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
    pdf += b"startxref\n" + str(xref_start).encode() + b"\n%%EOF\n"
    return pdf


def evidence_lines(dispute, extra_lines):
    # stand-in for what Leash will really file: the mandate + the approval record.
    # fictional store, fictional mandate
    transaction_ids = []
    for transaction in dispute.get("disputed_transactions", []):
        transaction_ids.append(str(transaction.get("seller_transaction_id")))
    lines = [
        "Leash proof of intent: Fernwood Supply Co",
        "",
        "Dispute: " + str(dispute.get("dispute_id")),
        "Transaction: " + ", ".join(transaction_ids),
        "",
        "Mandate (set by the account holder before the order):",
        "  Spend limit: 50.00 USD per order",
        "  Allowed: footwear, outdoor gear",
        "  Merchant: Fernwood Supply Co",
        "",
        "Order checked against mandate: clean match, auto-captured.",
    ]
    for line in extra_lines:
        lines.append(line)
    lines.append("This is a sandbox test document from the Leash spike.")
    return lines


def requested_evidence_types(dispute):
    # what PayPal wants from us. PayPal only accepts these, anything else gets
    # EVIDENCE_TYPE_IS_NOT_ALLOWED
    requested = []
    for evidence in dispute.get("evidences", []):
        if evidence.get("source") != "REQUESTED_FROM_SELLER":
            continue
        evidence_type = evidence.get("evidence_type")
        if evidence_type and evidence_type not in requested:
            requested.append(evidence_type)
    return requested


def pick_evidence_type(requested_types, type_override):
    if type_override:
        if requested_types and type_override not in requested_types:
            print("Heads up: forcing", type_override, "but PayPal asked for", requested_types)
            print("Expect EVIDENCE_TYPE_IS_NOT_ALLOWED.")
        return type_override
    if requested_types:
        if len(requested_types) > 1:
            print("PayPal asked for more than one type, sending the first:", requested_types[0])
        return requested_types[0]
    # nothing specific requested. OTHER is notes + documents, which is what Leash files
    return "OTHER"


def build_evidence(evidence_type, file_name):
    # one entry for the "input" part. every type gets notes + our PDF,
    # PROOF_OF_FULFILLMENT also needs tracking info
    notes = (
        "Buyer's shopping agent placed this order inside the buyer's pre-set mandate "
        "(limit 50.00 USD, outdoor gear, Fernwood Supply Co). Mandate attached."
    )
    evidence = {"evidence_type": evidence_type}
    pdf_extra_lines = []

    if evidence_type == "PROOF_OF_FULFILLMENT":
        # fictional carrier and tracking number. carrier_name has to be from PayPal's
        # enum, OTHER lets us name our own carrier in carrier_name_other
        tracking_number = "FWF" + str(uuid.uuid4().int)[:12]
        evidence["evidence_info"] = {
            "tracking_info": [
                {
                    "carrier_name": "OTHER",
                    "carrier_name_other": "Fernwood Freight",
                    "tracking_number": tracking_number,
                }
            ]
        }
        notes += " Shipped via Fernwood Freight, tracking " + tracking_number + "."
        pdf_extra_lines.append("Shipped via Fernwood Freight, tracking " + tracking_number)
    elif evidence_type == "PROOF_OF_REFUND":
        # needs evidence_info.refund_ids from a real refund we issued. not in this spike
        print("PROOF_OF_REFUND needs a refund id from an actual refund, this spike doesn't")
        print("issue refunds. Try --type with one of the other requested types.")
        sys.exit(1)

    evidence["notes"] = notes
    evidence["documents"] = [{"name": file_name}]
    return evidence, pdf_extra_lines


def provide_evidence(token, dispute_id, type_override=None):
    before = get_dispute(token, dispute_id)
    print("Before:")
    print_dispute(before)

    evidence_url = link_for(before, "provide_evidence")
    if not evidence_url:
        print("\nNo provide_evidence link on this dispute, so PayPal won't take evidence now.")
        print("Evidence is only allowed while status is WAITING_FOR_SELLER_RESPONSE.")
        sys.exit(1)

    requested_types = requested_evidence_types(before)
    print("\nPayPal requested from seller:", requested_types or "nothing specific")
    evidence_type = pick_evidence_type(requested_types, type_override)
    print("Sending evidence type:", evidence_type)

    file_name = "leash-proof-of-intent.pdf"
    evidence, pdf_extra_lines = build_evidence(evidence_type, file_name)
    pdf_bytes = build_tiny_pdf(evidence_lines(before, pdf_extra_lines))

    evidence_input = {"evidences": [evidence]}

    # multipart/form-data: an "input" part with the JSON, plus the file part.
    # schema names the file part "evidence-file", the docs sample uses "file1".
    # going with the schema since that's our source of truth
    multipart_parts = [
        ("input", (None, json.dumps(evidence_input), "application/json")),
        ("evidence-file", (file_name, pdf_bytes, "application/pdf")),
    ]

    headers = paypal_headers(token, idempotent=True)
    # let requests write the multipart Content-Type, it has to include the boundary
    del headers["Content-Type"]

    print("\nSending evidence (" + str(len(pdf_bytes)) + " byte PDF + notes)...")
    response = requests.post(evidence_url, headers=headers, files=multipart_parts, timeout=60)
    if response.status_code not in (200, 201):
        show_error("Provide evidence", response)
    print("PayPal said", response.status_code, "OK")

    after = get_dispute(token, dispute_id)
    print("\nAfter:")
    print_dispute(after)

    # quick diff so we can see exactly what moved
    print("\nWhat changed:")
    changed_anything = False
    fields_to_compare = [
        "status",
        "dispute_state",
        "dispute_life_cycle_stage",
        "seller_response_due_date",
        "update_time",
    ]
    for field in fields_to_compare:
        if before.get(field) != after.get(field):
            print("  " + field + ":", before.get(field), "->", after.get(field))
            changed_anything = True

    evidence_count_before = len(before.get("evidences", []))
    evidence_count_after = len(after.get("evidences", []))
    if evidence_count_before != evidence_count_after:
        print("  evidences:", evidence_count_before, "->", evidence_count_after)
        changed_anything = True

    actions_before = []
    for link in before.get("links", []):
        actions_before.append(link.get("rel"))
    actions_after = []
    for link in after.get("links", []):
        actions_after.append(link.get("rel"))
    if actions_before != actions_after:
        print("  actions:", actions_before, "->", actions_after)
        changed_anything = True

    if not changed_anything:
        print("  nothing visible yet. PayPal may process evidence async, run 'show' again soon")


if __name__ == "__main__":
    usage = "Usage: python spikes/spike3_disputes.py list | show <id> | evidence <id> [--type T]"
    command = sys.argv[1] if len(sys.argv) > 1 else None

    # check args before spending a token call
    if command == "list" and len(sys.argv) == 2:
        list_disputes(get_token())
    elif command == "show" and len(sys.argv) == 3:
        print_dispute(get_dispute(get_token(), sys.argv[2]))
    elif command == "evidence" and len(sys.argv) == 3:
        provide_evidence(get_token(), sys.argv[2])
    elif command == "evidence" and len(sys.argv) == 5 and sys.argv[3] == "--type":
        # e.g. --type OTHER. uppercase so --type other works too
        provide_evidence(get_token(), sys.argv[2], sys.argv[4].upper())
    else:
        print(usage)
        sys.exit(1)
