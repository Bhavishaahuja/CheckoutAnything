# run_intent_check: hard rules first, Claude only if they all pass. Anthropic client mocked,
# and the fake counts its calls because "didn't call Claude" is half the point

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.db import Base
from backend.app.intent.check import build_decision, leading_reason, run_intent_check
from backend.app.models import CheckedBy, Decision, Mandate, Order, Verdict

NOW = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
FAKE_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


class FakeAnthropic:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def with_options(self, **options):
        return self

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClock:
    # goes up by this many seconds every time it's read
    def __init__(self, step):
        self.now = 0.0
        self.step = step

    def __call__(self):
        self.now += self.step
        return self.now


def answer(verdict="match", risk_score=5, reason="Order matches the mandate.", fields=None):
    block = SimpleNamespace(
        type="tool_use",
        name="record_intent_check",
        input={
            "verdict": verdict,
            "risk_score": risk_score,
            "reason": reason,
            "mismatched_fields": fields or [],
        },
    )
    return SimpleNamespace(stop_reason="tool_use", content=[block])


def make_mandate(max_price="120.00", merchant="Fernwood Supply Co", expires_at=None):
    return Mandate(
        id=1,
        buyer_label="Sam",
        raw_request="Black trail runners, up to $120",
        rules={"item": "trail runners", "color": "black", "quantity": 1, "currency": "USD"},
        max_price=Decimal(max_price),
        max_price_inclusive=True,
        merchant=merchant,
        expires_at=expires_at,
    )


def make_order(total="98.00"):
    return Order(
        id=7,
        mandate_id=1,
        items=[{"name": "Trail runner", "color": "black", "size": "9", "quantity": 1,
                "unit_price": total}],
        total=Decimal(total),
        shipping_amount=Decimal("0.00"),
        currency="USD",
    )


# ---- hard rules decide it ----


def test_failed_rule_never_calls_claude():
    fake = FakeAnthropic()

    result = run_intent_check(make_mandate(), make_order(total="142.00"), client=fake, now=NOW)

    assert fake.requests == []
    assert result.verdict == Verdict.mismatch
    assert result.checked_by == CheckedBy.rules
    assert result.risk_score == 100
    assert result.reason == "Order is $142.00, mandate cap is $120.00"
    assert result.mismatched_fields == ["price"]


def test_several_failures_lead_with_the_top_one_and_count_the_rest():
    fake = FakeAnthropic()
    mandate = make_mandate(merchant="Ridgeline Outdoors", expires_at=NOW - timedelta(days=1))

    result = run_intent_check(mandate, make_order(total="142.00"), client=fake, now=NOW)

    assert fake.requests == []
    assert result.reason == (
        "Mandate says Ridgeline Outdoors, order is at Fernwood Supply Co (+2 more)"
    )
    # the full picture is still in the other fields
    assert result.mismatched_fields == ["price", "merchant", "expiry"]
    failed_reasons = []
    for rule_result in result.rule_results:
        if not rule_result.passed:
            failed_reasons.append(rule_result.reason)
    assert failed_reasons == [
        "Order is $142.00, mandate cap is $120.00",
        "Mandate says Ridgeline Outdoors, order is at Fernwood Supply Co",
        "Mandate expired 2026-11-03 12:00 UTC",
    ]


@pytest.mark.parametrize(("failing", "expected"), [
    (["price", "merchant"], "merchant reason (+1 more)"),
    (["price", "expiry"], "expiry reason (+1 more)"),
    (["price", "currency"], "currency reason (+1 more)"),
    (["merchant", "expiry"], "merchant reason (+1 more)"),
    (["currency", "expiry"], "expiry reason (+1 more)"),
    (["currency", "merchant"], "merchant reason (+1 more)"),
    (["price", "currency", "expiry", "merchant"], "merchant reason (+3 more)"),
    (["price"], "price reason"),
    # a future rule nobody gave a priority to still shows up
    (["new_rule"], "new_rule reason"),
    (["new_rule", "price"], "price reason (+1 more)"),
])
def test_reason_follows_the_rule_priority(failing, expected):
    # hand-built because the real rules can't fail in every combination: a currency mismatch
    # makes the price rule skip, for one
    reason_by_rule = {}
    for rule in failing:
        reason_by_rule[rule] = rule + " reason"

    assert leading_reason(failing, reason_by_rule) == expected


def test_rejected_order_includes_all_rule_results():
    result = run_intent_check(
        make_mandate(), make_order(total="142.00"), client=FakeAnthropic(), now=NOW
    )

    passed_by_rule = {}
    for rule_result in result.rule_results:
        passed_by_rule[rule_result.rule] = rule_result.passed
    assert passed_by_rule == {"price": False, "merchant": True, "expiry": True, "currency": True}


def test_no_client_is_built_when_rules_reject_it(monkeypatch):
    # with no client passed in, one only gets made if Claude is actually needed
    def fail_if_called(api_key):
        raise AssertionError("built a client for an order the rules already rejected")

    monkeypatch.setattr("backend.app.mandate_parser.make_client", fail_if_called)

    result = run_intent_check(make_mandate(), make_order(total="142.00"), now=NOW)

    assert result.checked_by == CheckedBy.rules
    assert result.verdict == Verdict.mismatch


# ---- Claude decides it ----


def test_clean_rules_go_to_claude():
    fake = FakeAnthropic([answer("match", 5, "Black trail runners, as asked.")])

    result = run_intent_check(make_mandate(), make_order(), client=fake, now=NOW)

    assert len(fake.requests) == 1
    assert result.verdict == Verdict.match
    assert result.checked_by == CheckedBy.ai
    assert result.risk_score == 5
    assert result.reason == "Black trail runners, as asked."
    assert result.mismatched_fields == []
    assert len(result.rule_results) == 4
    for rule_result in result.rule_results:
        assert rule_result.passed is True


def test_claude_mismatch_comes_through():
    fake = FakeAnthropic([answer("mismatch", 85, "Ordered red, mandate says black", ["color"])])

    result = run_intent_check(make_mandate(), make_order(), client=fake, now=NOW)

    assert result.verdict == Verdict.mismatch
    assert result.checked_by == CheckedBy.ai
    assert result.risk_score == 85
    assert result.mismatched_fields == ["color"]


def test_claude_failing_still_counts_as_checked_by_ai():
    fake = FakeAnthropic([anthropic.APITimeoutError(request=FAKE_REQUEST)])

    result = run_intent_check(make_mandate(), make_order(), client=fake, now=NOW)

    assert result.verdict == Verdict.unsure
    assert result.risk_score == 50
    assert result.reason == "Couldn't verify automatically, please review"
    assert result.checked_by == CheckedBy.ai
    # the rules did run and pass, so that stays on the record
    assert len(result.rule_results) == 4


def test_rules_crashing_fails_closed_without_calling_claude():
    # rules that aren't a dict make the currency rule blow up
    fake = FakeAnthropic()
    mandate = make_mandate()
    mandate.rules = None

    result = run_intent_check(mandate, make_order(), client=fake, now=NOW)

    assert fake.requests == []
    assert result.verdict == Verdict.unsure
    assert result.risk_score == 50
    assert result.reason == "Couldn't verify automatically, please review"
    assert result.checked_by == CheckedBy.rules
    assert result.rule_results == []


def test_building_the_client_failing_fails_closed(monkeypatch):
    def broken_client(api_key):
        raise RuntimeError("bad config")

    monkeypatch.setattr("backend.app.mandate_parser.make_client", broken_client)

    result = run_intent_check(make_mandate(), make_order(), now=NOW)

    assert result.verdict == Verdict.unsure


# ---- latency ----


@pytest.mark.parametrize("responses", [
    [answer()],
    [anthropic.APITimeoutError(request=FAKE_REQUEST)],
])
def test_latency_is_recorded_when_claude_runs(responses):
    fake = FakeAnthropic(responses)

    result = run_intent_check(
        make_mandate(), make_order(), client=fake, now=NOW, clock=FakeClock(0.25)
    )

    # started at one read, finished at the next
    assert result.latency_ms == 250


def test_latency_is_recorded_when_rules_reject_it():
    result = run_intent_check(
        make_mandate(), make_order(total="142.00"), client=FakeAnthropic(), now=NOW,
        clock=FakeClock(0.25),
    )

    assert result.latency_ms == 250


def test_latency_is_recorded_when_the_rules_crash():
    mandate = make_mandate()
    mandate.rules = None

    result = run_intent_check(
        mandate, make_order(), client=FakeAnthropic(), now=NOW, clock=FakeClock(0.25)
    )

    assert result.latency_ms == 250


# ---- saving the result ----


@pytest.mark.parametrize(("total", "responses", "verdict", "risk_score", "checked_by"), [
    ("142.00", [], "mismatch", 100, "rules"),
    ("98.00", [answer("mismatch", 85, "Wrong color", ["color"])], "mismatch", 85, "ai"),
    ("98.00", [answer("match", 5)], "match", 5, "ai"),
    # clamped on the way in
    ("98.00", [answer("unsure", 150, "Can't tell.")], "unsure", 100, "ai"),
    # failing closed is a real decision too, the human needs to see why it's in their queue
    ("98.00", [anthropic.APITimeoutError(request=FAKE_REQUEST)], "unsure", 50, "ai"),
])
def test_full_result_is_saved_on_the_decision_row(total, responses, verdict, risk_score,
                                                  checked_by):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    mandate = make_mandate()
    order = make_order(total=total)

    result = run_intent_check(mandate, order, client=FakeAnthropic(responses), now=NOW)

    with Session(engine) as session:
        session.add_all([mandate, order, build_decision(order, result)])
        session.commit()

    with Session(engine) as session:
        saved = session.query(Decision).one()
        assert saved.order_id == 7
        assert saved.verdict == Verdict(verdict)
        assert saved.risk_score == risk_score
        assert saved.reason == result.reason
        assert saved.checked_by == CheckedBy(checked_by)
        assert saved.mismatched_fields == result.mismatched_fields
        assert saved.latency_ms == result.latency_ms
        assert len(saved.rule_results) == 4
        assert set(saved.rule_results[0]) == {"rule", "passed", "reason"}
