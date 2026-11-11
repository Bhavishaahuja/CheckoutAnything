# backend/scripts/demo_dispute.py: the parts that don't talk to PayPal. what it sends is checked
# against the shapes in PayPal's docs, and when it calls a dispute ready has to agree with what
# Check's own submit needs (disputes.evidence_blocker and choose_evidence_type)

import base64
import json

from backend.app import disputes
from backend.scripts import demo_dispute


def decode(part):
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def test_auth_assertion_is_the_unsigned_jwt_the_sandbox_takes():
    token = demo_dispute.auth_assertion("client-123", "buyer@example.com")
    header, payload, signature = token.split(".")
    assert decode(header) == {"alg": "none", "typ": "JWT"}
    assert decode(payload) == {"iss": "client-123", "email": "buyer@example.com"}
    assert signature == ""


def test_create_input_is_not_as_described_for_the_whole_payment():
    body = demo_dispute.create_dispute_input("9AB12345CD678901E", "146.00")
    assert body["disputed_transactions"] == [{"buyer_transaction_id": "9AB12345CD678901E"}]
    assert body["reason"] == "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"
    assert body["dispute_amount"] == {"currency_code": "USD", "value": "146.00"}


def details(stage, status, rels, requested=None):
    evidences = []
    for evidence_type in requested or []:
        evidences.append({"evidence_type": evidence_type, "source": "REQUESTED_FROM_SELLER"})
    links = [{"rel": "self"}]
    for rel in rels:
        links.append({"rel": rel})
    return {"dispute_id": "PP-R-TEST-1", "dispute_life_cycle_stage": stage, "status": status,
            "links": links, "evidences": evidences}


def test_ready_exactly_when_check_can_file():
    cases = [
        details("INQUIRY", "WAITING_FOR_SELLER_RESPONSE", ["provide-evidence"]),
        details("CHARGEBACK", "WAITING_FOR_SELLER_RESPONSE", ["provide_evidence"], ["OTHER"]),
        details("CHARGEBACK", "UNDER_REVIEW", ["require-evidence"]),
        details("INQUIRY", "WAITING_FOR_BUYER_RESPONSE", ["escalate"]),
        details("INQUIRY", "WAITING_FOR_SELLER_RESPONSE", []),
        details("CHARGEBACK", "WAITING_FOR_SELLER_RESPONSE", ["provide-evidence"],
                ["PROOF_OF_FULFILLMENT"]),
    ]
    for case in cases:
        ready, _message = demo_dispute.readiness(case)
        check_would_file = (
            disputes.evidence_blocker(case) is None
            and disputes.choose_evidence_type(case)[0] is not None
        )
        assert ready == check_would_file, case


def test_next_step_escalates_an_inquiry_then_asks_for_seller_evidence():
    inquiry = details("INQUIRY", "OPEN", ["escalate", "send-message"])
    assert demo_dispute.next_step(inquiry) == "escalate"
    claim = details("CHARGEBACK", "UNDER_REVIEW", ["require-evidence"])
    assert demo_dispute.next_step(claim) == "require-evidence"
    ready = details("CHARGEBACK", "WAITING_FOR_SELLER_RESPONSE", ["provide-evidence"])
    assert demo_dispute.next_step(ready) is None
    # under review with no link: nothing to do but wait
    assert demo_dispute.next_step(details("CHARGEBACK", "UNDER_REVIEW", [])) is None


def test_only_proof_types_is_not_ready_and_says_why():
    case = details("CHARGEBACK", "WAITING_FOR_SELLER_RESPONSE", ["provide-evidence"],
                   ["PROOF_OF_FULFILLMENT"])
    ready, message = demo_dispute.readiness(case)
    assert ready is False
    assert "PROOF_OF_FULFILLMENT" in message
