import copy

import requests

from backend.app.paypal_client import PayPalError
from backend.app.verifier import MAX_REPAIRS, verify_store
from backend.tests.fakes import (
    HOLLOWBROOK_SPEC,
    FakeAI,
    FakePayPal,
    MemoryRecorder,
    demo_page,
    spec_copy,
)

PAGE = demo_page("hollowbrook-bakery").text


def run(spec_data, ai=None, paypal=None):
    events = []

    def emit(event_type, message, item_id=None, data=None):
        events.append({"type": event_type, "message": message, "item_id": item_id,
                       "data": data or {}})

    paypal = paypal or FakePayPal()
    ai = ai or FakeAI(spec_data)
    recorder = MemoryRecorder()
    spec, counts = verify_store(7, spec_copy(spec_data), 1, PAGE, ai, paypal, emit, recorder)
    return spec, counts, events, paypal, ai, recorder


def types_for(events, item_id):
    return [event["type"] for event in events if event["item_id"] == item_id]


def with_wrong_rye_price():
    data = copy.deepcopy(HOLLOWBROOK_SPEC)
    # the classic mistake: took the crossed-out price
    data["items"][1]["unit_price"] = "8.00"
    return data


def test_a_correct_spec_verifies_everything_in_order():
    spec, counts, events, paypal, _ai, recorder = run(HOLLOWBROOK_SPEC)
    assert counts == {"verified": 4, "failed": 0, "unavailable": 1}

    verified = [event["item_id"] for event in events if event["type"] == "item.verified"]
    assert verified == ["sourdough-loaf", "seeded-rye", "cinnamon-morning-bun", "olive-focaccia"]
    # one real order per item, for exactly one unit at the spec price, never paid
    assert len(paypal.created_bodies) == 4
    first = paypal.created_bodies[0]
    assert first["intent"] == "CAPTURE"
    assert "payment_source" not in first
    unit = first["purchase_units"][0]
    assert unit["amount"]["value"] == "9.00"
    assert unit["amount"]["breakdown"]["item_total"]["value"] == "9.00"
    assert unit["items"][0] == {
        "name": "Sourdough Loaf", "quantity": "1",
        "unit_amount": {"currency_code": "USD", "value": "9.00"},
    }
    for event in events:
        if event["type"] == "item.verified":
            assert event["data"]["paypal_order_id"].startswith("ORDER")
    assert len(recorder.runs) == 4


def test_the_sold_out_item_is_never_checked_or_ordered():
    _spec, _counts, events, paypal, _ai, _recorder = run(HOLLOWBROOK_SPEC)
    assert types_for(events, "butter-croissant") == []
    for body in paypal.created_bodies:
        assert body["purchase_units"][0]["items"][0]["name"] != "Butter Croissant"


def test_a_wrong_price_fails_the_page_check_and_gets_repaired():
    fixed = copy.deepcopy(HOLLOWBROOK_SPEC["items"][1])
    ai = FakeAI(HOLLOWBROOK_SPEC, {"seeded-rye": [(fixed, "Used the current price, not $8")]})
    spec, counts, events, paypal, ai, recorder = run(with_wrong_rye_price(), ai=ai)

    assert counts["verified"] == 4 and counts["failed"] == 0
    assert types_for(events, "seeded-rye") == [
        "item.checking", "item.failed", "item.repairing", "item.checking", "item.verified",
    ]
    failed = [event for event in events if event["type"] == "item.failed"][0]
    assert failed["data"]["page_check_ok"] is False
    assert failed["data"]["final"] is False
    assert "7.00" in failed["data"]["reason"]
    # Claude got the exact reason
    assert ai.repair_calls == [("seeded-rye", failed["data"]["reason"])]
    # no PayPal order was made for the price the page didn't back up
    names = [body["purchase_units"][0]["items"][0]["name"] for body in paypal.created_bodies]
    assert names.count("Seeded Rye") == 1
    # the repair is a new spec version, and the note says what changed
    assert spec.find_item("seeded-rye").unit_price == "7.00"
    assert recorder.specs[0][0] == 2
    assert "Used the current price" in spec.extraction_notes[-1]


def test_it_gives_up_after_three_repairs_and_says_why():
    # FakeAI with no repairs hands the same broken item back every time
    spec, counts, events, _paypal, ai, _recorder = run(with_wrong_rye_price())

    assert counts["failed"] == 1 and counts["verified"] == 3
    rye = types_for(events, "seeded-rye")
    assert rye.count("item.repairing") == MAX_REPAIRS
    assert rye.count("item.checking") == MAX_REPAIRS + 1
    assert "item.verified" not in rye
    assert len(ai.repair_calls) == MAX_REPAIRS
    last = [e for e in events if e["item_id"] == "seeded-rye" and e["type"] == "item.failed"][-1]
    assert last["data"]["final"] is True
    assert last["data"]["reason"]
    # the items after it still got their turn
    assert "item.verified" in types_for(events, "olive-focaccia")


def test_a_repair_cant_rename_the_item():
    fixed = copy.deepcopy(HOLLOWBROOK_SPEC["items"][1])
    fixed["id"] = "something-else"
    ai = FakeAI(HOLLOWBROOK_SPEC, {"seeded-rye": [(fixed, "fixed")]})
    spec, _counts, _events, _paypal, _ai, _recorder = run(with_wrong_rye_price(), ai=ai)
    assert spec.find_item("seeded-rye") is not None
    assert spec.find_item("something-else") is None


def test_paypal_holding_a_different_name_is_a_failure():
    paypal = FakePayPal()
    paypal.rename["Seeded Rye"] = "Seeded Ry"
    _spec, counts, events, _paypal, _ai, _recorder = run(HOLLOWBROOK_SPEC, paypal=paypal)
    assert counts["failed"] == 1
    failed = [e for e in events if e["type"] == "item.failed"][0]
    assert failed["data"]["page_check_ok"] is True
    assert failed["data"]["paypal_check_ok"] is False
    assert "Seeded Ry" in failed["data"]["reason"]


def test_paypal_being_down_fails_without_bothering_claude():
    paypal = FakePayPal()
    paypal.fail_with = requests.ConnectionError("down")
    _spec, counts, events, _paypal, ai, _recorder = run(HOLLOWBROOK_SPEC, paypal=paypal)
    assert counts == {"verified": 0, "failed": 4, "unavailable": 1}
    assert ai.repair_calls == []
    for event in events:
        if event["type"] == "item.failed":
            assert event["data"]["final"] is True
            assert "PayPal" in event["data"]["reason"]


def test_bad_paypal_credentials_are_not_repairable():
    paypal = FakePayPal()
    paypal.fail_with = PayPalError(401, name="invalid_client", message="Client auth failed")
    _spec, counts, _events, _paypal, ai, _recorder = run(HOLLOWBROOK_SPEC, paypal=paypal)
    assert counts["verified"] == 0
    assert ai.repair_calls == []


def test_a_repair_that_marks_the_item_unavailable_stops_there():
    gone = copy.deepcopy(HOLLOWBROOK_SPEC["items"][1])
    gone["available"] = False
    ai = FakeAI(HOLLOWBROOK_SPEC, {"seeded-rye": [(gone, "Not clearly priced")]})
    spec, counts, events, _paypal, _ai, _recorder = run(with_wrong_rye_price(), ai=ai)
    assert counts == {"verified": 3, "failed": 0, "unavailable": 2}
    assert spec.find_item("seeded-rye").available is False
    assert "item.verified" not in types_for(events, "seeded-rye")


def test_a_failed_claude_call_leaves_the_item_failed():
    class BrokenAI(FakeAI):
        def repair_item(self, item, reason, page_text):
            raise RuntimeError("overloaded")

    _spec, counts, events, _paypal, _ai, _recorder = run(
        with_wrong_rye_price(), ai=BrokenAI(HOLLOWBROOK_SPEC)
    )
    assert counts["failed"] == 1
    last = [e for e in events if e["item_id"] == "seeded-rye"][-1]
    assert last["type"] == "item.failed" and last["data"]["final"] is True
    assert "overloaded" in last["data"]["reason"]
