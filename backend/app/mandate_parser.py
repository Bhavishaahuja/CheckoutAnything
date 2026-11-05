# Calls Claude to turn the shopper's words into mandate fields.
#
# Claude Sonnet 5.5 rejects forced tool_choice ("any" / "tool" return a 400), so we use
# tool_choice auto + a prompt that says to always call record_mandate, and strict: true on
# the tool so the arguments always match the schema. auto doesn't guarantee a call, so we
# check for one and retry once.

from datetime import datetime, timezone
from decimal import Decimal

import anthropic

from backend.app.prompts import mandate as mandate_prompt

# server-side fallback: if Sonnet 5.5 declines, fallbacks="default" retries on another model
# inside the same call. Claude API only
FALLBACK_BETA = "server-side-fallback-2026-07-01"

MAX_ATTEMPTS = 2


class MandateParseError(Exception):
    pass


def make_client(api_key):
    # empty key falls back to the SDK's own lookup (ANTHROPIC_API_KEY, ant auth profile)
    if api_key:
        return anthropic.Anthropic(api_key=api_key)
    return anthropic.Anthropic()


def call_claude(client, request_text, now):
    return client.beta.messages.create(
        model=mandate_prompt.MODEL,
        max_tokens=16000,
        system=mandate_prompt.SYSTEM_PROMPT,
        tools=[mandate_prompt.RECORD_MANDATE_TOOL],
        tool_choice={"type": "auto"},
        output_config={"effort": mandate_prompt.EFFORT},
        betas=[FALLBACK_BETA],
        fallbacks="default",
        messages=[
            {
                "role": "user",
                "content": mandate_prompt.build_user_message(request_text, now),
            }
        ],
    )


def find_tool_input(response):
    for block in response.content:
        if block.type == "tool_use" and block.name == mandate_prompt.RECORD_MANDATE_TOOL["name"]:
            return block.input
    return None


def parse_mandate(client, request_text, now=None):
    # returns the record_mandate fields as a dict (missing fields are None)
    if now is None:
        now = datetime.now(timezone.utc)

    for _ in range(MAX_ATTEMPTS):
        response = call_claude(client, request_text, now)

        # always check stop_reason before trusting content
        if response.stop_reason == "refusal":
            raise MandateParseError("Claude declined to parse this request")

        tool_input = find_tool_input(response)
        if tool_input is not None:
            return clean_fields(tool_input)
        # no tool call this time, go around once more

    raise MandateParseError(
        "Claude didn't call record_mandate after " + str(MAX_ATTEMPTS) + " tries"
    )


def clean_fields(tool_input):
    # strict mode already guarantees the shape, this just fills gaps and tidies types
    fields = {}
    for name in mandate_prompt.RECORD_MANDATE_TOOL["input_schema"]["properties"]:
        fields[name] = tool_input.get(name)

    # quantity defaults to 1 when the shopper didn't say
    if fields["quantity"] is None:
        fields["quantity"] = 1

    # inclusive unless the model clearly said otherwise ("under $X")
    if fields["max_price_inclusive"] is not False:
        fields["max_price_inclusive"] = True

    # blank strings are the same as "not given"
    for name, value in fields.items():
        if isinstance(value, str) and not value.strip():
            fields[name] = None

    # "from Fernwood Supply Co." sometimes keeps the sentence's full stop
    if fields["merchant"]:
        fields["merchant"] = fields["merchant"].strip().rstrip(".")

    # "eur" and "EUR" are the same currency. something that isn't a real code stays as it
    # is on purpose: it won't match the order, so a human gets to look at it
    if fields["currency"]:
        fields["currency"] = fields["currency"].strip().upper()

    return fields


def max_price_decimal(fields):
    if fields.get("max_price") is None:
        return None
    # via str so 119.99 doesn't turn into 119.98999999...
    return Decimal(str(fields["max_price"])).quantize(Decimal("0.01"))


def expires_at_datetime(fields):
    value = fields.get("expires_at")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        # model gave something that isn't a date, keep it in rules but don't store it
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
