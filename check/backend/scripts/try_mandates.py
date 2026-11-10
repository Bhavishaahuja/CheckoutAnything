# try_mandates.py
# Send sample shopper requests through the real mandate parser and print what Claude made
# of them, so we can eyeball quality while tuning backend/app/prompts/mandate.py.
#
# Run from the repo root:
#   python backend/scripts/try_mandates.py                              calls Claude directly
#   python backend/scripts/try_mandates.py --api http://127.0.0.1:8000  goes through POST /mandates
#
# Direct mode needs only ANTHROPIC_API_KEY in .env. --api mode needs the server running
# (uvicorn backend.app.main:app --reload) and a database. Each run is 7 real Claude calls.

import os
import sys

# make "backend.app" importable when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests  # noqa: E402

from backend.app import mandate_parser  # noqa: E402
from backend.app.config import get_settings  # noqa: E402

# mix of clean and vague, all fictional
SAMPLES = [
    "Get me black trail runners, women's size 9, under $120, from Fernwood Supply Co, "
    "sometime this week.",
    "Two packs of AA batteries, $15 max all in including shipping, by Friday.",
    "Something warm for camping next month, nothing over 80 bucks.",
    "Reorder the usual coffee beans.",
    "Order a rain jacket, size M, navy or forest green, from Fernwood Supply Co. Max £60. "
    "Nothing with down in it.",
    "Three pairs of wool hiking socks, up to $30 total.",
    "A rain jacket under 100 euros from Fernwood.",
]

# what max_price_inclusive should come out as for each sample, so a wrong one stands out.
# "under" -> False, "max" / "nothing over" / "up to" -> True, no price -> True
EXPECTED_INCLUSIVE = [False, True, True, True, True, True, False]

# same idea for currency. "$", "bucks" -> USD, "£" -> GBP, "euros" -> EUR, no price -> None
EXPECTED_CURRENCY = ["USD", "USD", "USD", None, "GBP", "USD", "EUR"]

COLUMNS = ["item", "category", "color", "size", "quantity", "max_price", "currency",
           "max_price_inclusive", "merchant", "expires_at", "notes"]
CELL_WIDTH = 22


def parse_directly(client, request_text):
    return mandate_parser.parse_mandate(client, request_text)


def parse_through_api(base_url, request_text):
    response = requests.post(
        base_url.rstrip("/") + "/mandates",
        json={"buyer_label": "try_mandates", "request_text": request_text},
        headers={"X-API-Key": get_settings().agent_api_key},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["rules"]


def cell(value):
    text = "-" if value is None else str(value)
    if len(text) > CELL_WIDTH:
        text = text[: CELL_WIDTH - 2] + ".."
    return text.ljust(CELL_WIDTH)


def print_table(results):
    header = "#  " + "".join(cell(name) for name in COLUMNS)
    print(header)
    print("-" * len(header))
    for number, fields in enumerate(results, start=1):
        row = str(number).ljust(3)
        for name in COLUMNS:
            row += cell(fields.get(name))
        print(row)


def main():
    # Windows consoles default to cp1252 and mangle things like the pound sign
    sys.stdout.reconfigure(encoding="utf-8")

    api_url = None
    if len(sys.argv) == 3 and sys.argv[1] == "--api":
        api_url = sys.argv[2]
    elif len(sys.argv) != 1:
        print("Usage: python backend/scripts/try_mandates.py [--api http://127.0.0.1:8000]")
        sys.exit(1)

    client = None
    if api_url is None:
        client = mandate_parser.make_client(get_settings().anthropic_api_key)

    results = []
    for number, request_text in enumerate(SAMPLES, start=1):
        print(str(number) + ". " + request_text)
        try:
            if api_url:
                fields = parse_through_api(api_url, request_text)
            else:
                fields = parse_directly(client, request_text)
        except Exception as error:  # noqa: BLE001  (show the failure, keep going)
            print("   failed:", error)
            fields = {}
        results.append(fields)

    print()
    print_table(results)

    # notes get cut off in the table, print them in full
    print()
    for number, fields in enumerate(results, start=1):
        if fields.get("notes"):
            print(str(number) + ". notes: " + fields["notes"])

    print()
    mismatches = 0
    for number, fields in enumerate(results, start=1):
        expected = EXPECTED_INCLUSIVE[number - 1]
        if fields.get("max_price_inclusive") != expected:
            mismatches += 1
            print(
                str(number) + ". max_price_inclusive: expected " + str(expected)
                + ", got " + str(fields.get("max_price_inclusive"))
            )
    print("max_price_inclusive:", len(results) - mismatches, "of", len(results), "as expected")

    currency_mismatches = 0
    for number, fields in enumerate(results, start=1):
        expected = EXPECTED_CURRENCY[number - 1]
        if fields.get("currency") != expected:
            currency_mismatches += 1
            print(
                str(number) + ". currency: expected " + str(expected)
                + ", got " + str(fields.get("currency"))
            )
    print("currency:", len(results) - currency_mismatches, "of", len(results), "as expected")


if __name__ == "__main__":
    main()
