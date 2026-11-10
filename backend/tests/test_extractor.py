import copy

import pytest

from backend.app.config import CLAUDE_MODEL
from backend.app.extractor import ClaudeExtractor, ExtractionError
from backend.app.spec import SpecError, parse_item
from backend.tests.fakes import (
    HOLLOWBROOK_SPEC,
    FakeClaude,
    Reply,
    demo_page,
    text_block,
    tool_block,
)

PAGE = demo_page("hollowbrook-bakery")


def claude_spec():
    # what Claude sends: no spec_version or source_url, those are ours
    data = copy.deepcopy(HOLLOWBROOK_SPEC)
    del data["spec_version"]
    del data["source_url"]
    return data


def test_extract_builds_a_validated_spec_from_the_tool_call():
    client = FakeClaude([Reply([tool_block("submit_store_spec", claude_spec())], "tool_use")])
    spec = ClaudeExtractor("key", client=client).extract_spec(PAGE)

    assert spec.merchant.name == "Hollowbrook Bakery"
    assert spec.source_url == PAGE.url
    request = client.requests[0]
    assert request["model"] == CLAUDE_MODEL
    # this model rejects a forced tool choice, so it has to be auto
    assert request["tool_choice"]["type"] == "auto"
    assert request["tools"][0]["strict"] is True
    assert PAGE.text in request["messages"][0]["content"]


def test_claude_cant_set_the_source_url():
    data = claude_spec()
    data["source_url"] = "https://evil.example/"
    client = FakeClaude([Reply([tool_block("submit_store_spec", data)], "tool_use")])
    spec = ClaudeExtractor("key", client=client).extract_spec(PAGE)
    assert spec.source_url == PAGE.url


def test_a_reply_without_a_tool_call_gets_one_nudge():
    client = FakeClaude([
        Reply([text_block("Here is what I found...")]),
        Reply([tool_block("submit_store_spec", claude_spec())], "tool_use"),
    ])
    spec = ClaudeExtractor("key", client=client).extract_spec(PAGE)
    assert len(spec.items) == 5
    assert len(client.requests) == 2
    assert "submit_store_spec" in client.requests[1]["messages"][-1]["content"]


def test_two_replies_without_a_tool_call_is_an_error():
    client = FakeClaude([Reply([text_block("no")]), Reply([text_block("still no")])])
    with pytest.raises(ExtractionError):
        ClaudeExtractor("key", client=client).extract_spec(PAGE)


def test_an_invalid_spec_is_sent_back_once_with_the_reason():
    bad = claude_spec()
    bad["items"][0]["unit_price"] = "9"
    client = FakeClaude([
        Reply([tool_block("submit_store_spec", bad)], "tool_use"),
        Reply([tool_block("submit_store_spec", claude_spec())], "tool_use"),
    ])
    spec = ClaudeExtractor("key", client=client).extract_spec(PAGE)
    assert spec.items[0].unit_price == "9.00"
    assert "rejected by validation" in client.requests[1]["messages"][0]["content"]


def test_a_spec_that_is_invalid_twice_is_rejected():
    bad = claude_spec()
    bad["items"][0]["unit_price"] = "9"
    client = FakeClaude([
        Reply([tool_block("submit_store_spec", bad)], "tool_use"),
        Reply([tool_block("submit_store_spec", copy.deepcopy(bad))], "tool_use"),
    ])
    with pytest.raises(SpecError):
        ClaudeExtractor("key", client=client).extract_spec(PAGE)


def test_refusal_and_running_out_of_tokens_are_errors():
    for stop_reason in ("refusal", "max_tokens"):
        client = FakeClaude([Reply([], stop_reason)])
        with pytest.raises(ExtractionError):
            ClaudeExtractor("key", client=client).extract_spec(PAGE)


def test_repair_sends_the_reason_and_returns_the_item_and_note():
    fixed = copy.deepcopy(HOLLOWBROOK_SPEC["items"][1])
    client = FakeClaude([Reply([tool_block(
        "submit_repaired_item", {"item": fixed, "repair_note": "Used $7, $8 is crossed out"}
    )], "tool_use")])
    broken = copy.deepcopy(fixed)
    broken["unit_price"] = "8.00"

    item, note = ClaudeExtractor("key", client=client).repair_item(
        parse_item(broken), "The page says 7.00 but the spec says 8.00", PAGE.text
    )
    assert item.unit_price == "7.00"
    assert note == "Used $7, $8 is crossed out"
    sent = client.requests[0]["messages"][0]["content"]
    assert "The page says 7.00 but the spec says 8.00" in sent
    assert '"unit_price": "8.00"' in sent
