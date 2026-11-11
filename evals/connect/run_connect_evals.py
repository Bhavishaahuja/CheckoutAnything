# run_connect_evals.py
# Scores Connect (store URL -> Claude writes the spec -> fixed verifier -> verified items) against
# hand-written ground truth in evals/connect/golden/. One golden file per case:
#   stores     the three demo stores, built by hand from demo-stores/<slug>/index.html
#   negatives  example.com (live) and three local pages in evals/connect/fixtures/: no prices,
#              a prompt injection, and prices that only exist in an image or a script
#
# Every case goes through the real pipeline, connect.run_connect, the same function the API runs
# in its background thread: the real fetcher (SSRF guard and all), live Claude, the real verifier
# and the real review flags. Nothing in backend/app is changed or patched. What's swapped in is
# only what create_app lets you swap: the database, the PayPal client and the Claude client
# (wrapped to count calls and tokens, the calls themselves are unchanged).
#
# Why in-process (--local) and not the hosted API (--api):
#   - the API has no way to delete a store, so every eval store would stay in the demo database
#   - the API treats a URL it already connected as the same store, so a demo store URL would
#     hand back the existing demo store instead of running a fresh extraction
#   - a verified item with no flags goes live on its own, so eval items would land in the
#     catalog the shopping agent reads
#   - the hosted API can't reach the fixture pages on this machine
# So --api refuses to run and says why.
#
# Leaving no demo state behind:
#   - a throwaway sqlite file in a temp folder, deleted at the end (--keep-db keeps it)
#   - eval store ids start at 900001, so the verifier's custom_id reads verify-9000xx-<item>
#   - RECORD_FIXTURES is forced off, so backend/fixtures isn't touched
#   - nothing is published to PayPal and nothing is paid or captured. "Live on PayPal" in the app
#     is a column in the database, and this database is thrown away
#   - the verifier's own check creates real PayPal sandbox orders (never captured, no payer, they
#     lapse after 6 hours). With --paypal sandbox (the default) every one is listed in the
#     results. --paypal echo uses a stand-in that hands back what it was sent, no PayPal at all
#
# Run from the repo root, in cmd:
#   .venv\Scripts\python.exe evals\connect\run_connect_evals.py
#   .venv\Scripts\python.exe evals\connect\run_connect_evals.py --runs 1
#   .venv\Scripts\python.exe evals\connect\run_connect_evals.py --cases prompt-injection no-prices
#   .venv\Scripts\python.exe evals\connect\run_connect_evals.py --paypal echo
#
# Needs ANTHROPIC_API_KEY in .env, plus PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET for
# --paypal sandbox. A full run (every case) saves results/latest.json and results/latest.md.
# A partial run only prints, unless --out says where to save.

import argparse
import functools
import http.server
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

# make "backend.app" importable when run as a script
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

import anthropic  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.app import models, review, shop  # noqa: E402
from backend.app.config import CLAUDE_MODEL, Settings  # noqa: E402
from backend.app.connect import run_connect  # noqa: E402
from backend.app.db import Base, make_engine  # noqa: E402
from backend.app.events import bus  # noqa: E402
from backend.app.extractor import ClaudeExtractor  # noqa: E402
from backend.app.paypal_client import client_from_settings  # noqa: E402

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
GOLDEN_DIR = os.path.join(EVALS_DIR, "golden")
FIXTURES_DIR = os.path.join(EVALS_DIR, "fixtures")
RESULTS_DIR = os.path.join(EVALS_DIR, "results")
DEMO_STORES_DIR = os.path.join(REPO_ROOT, "demo-stores")

# eval stores get ids from here up, far away from anything the demo database hands out
EVAL_STORE_ID_BASE = 900000

# the order cases show up in the report
CASE_ORDER = [
    "fernwood-thistle-goods", "quill-pipkin-studio", "hollowbrook-bakery",
    "example-com", "no-prices", "prompt-injection", "price-in-image-js",
]

API_REFUSAL = (
    "--api isn't supported. The hosted API can't delete a store, reuses the existing demo store "
    "for a demo URL instead of running a fresh extraction, auto-publishes clean verified items "
    "into the catalog the shopping agent reads, and can't reach the local fixture pages. "
    "Use --local (the default), which runs the same pipeline in-process on a throwaway database."
)


# ---- golden files ----


def load_cases():
    cases = []
    for name in os.listdir(GOLDEN_DIR):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(GOLDEN_DIR, name), encoding="utf-8") as f:
            cases.append(json.load(f))

    def position(case):
        if case["case"] in CASE_ORDER:
            return CASE_ORDER.index(case["case"])
        return len(CASE_ORDER)

    cases.sort(key=position)
    return cases


# ---- local pages ----


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def start_page_server(directory):
    # serves a folder on 127.0.0.1 on a free port, in a background thread
    handler = functools.partial(QuietHandler, directory=directory)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


# ---- counting what Claude does ----


class Tally:
    def __init__(self):
        self.lock = threading.Lock()
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.models = set()

    def add(self, response):
        usage = getattr(response, "usage", None)
        with self.lock:
            if usage is not None:
                self.input_tokens += getattr(usage, "input_tokens", 0) or 0
                self.input_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
                self.input_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
                self.output_tokens += getattr(usage, "output_tokens", 0) or 0
            model = getattr(response, "model", None)
            if model:
                self.models.add(model)

    def count_call(self):
        with self.lock:
            self.calls += 1


class CountingMessages:
    # passes every call straight through, just counts it
    def __init__(self, real_messages, tally):
        self.real_messages = real_messages
        self.tally = tally

    def create(self, **kwargs):
        self.tally.count_call()
        response = self.real_messages.create(**kwargs)
        self.tally.add(response)
        return response


class CountingClient:
    # looks like anthropic.Anthropic to ClaudeExtractor, which only uses client.beta.messages
    def __init__(self, api_key, tally):
        real = anthropic.Anthropic(api_key=api_key)
        self.beta = SimpleNamespace(messages=CountingMessages(real.beta.messages, tally))


def counting_ai_factory(tally):
    def factory(settings):
        return ClaudeExtractor(settings.anthropic_api_key, client=CountingClient(
            settings.anthropic_api_key, tally))
    return factory


# ---- PayPal ----


class RecordingPayPal:
    # the real sandbox client, with every order it creates written down for the report.
    # the verifier never sends a payment source, refusing one here just makes sure of it
    def __init__(self, real):
        self.real = real
        self.lock = threading.Lock()
        self.orders = []

    def create_order(self, body, request_id=None):
        if "payment_source" in body:
            raise RuntimeError("The eval never pays for anything")
        order = self.real.create_order(body, request_id)
        unit = body["purchase_units"][0]
        with self.lock:
            self.orders.append({
                "paypal_order_id": order.get("id"),
                "custom_id": unit.get("custom_id"),
                "item_name": unit["items"][0]["name"],
                "amount": unit["amount"]["value"],
                "currency": unit["amount"]["currency_code"],
                "status": order.get("status"),
            })
        return order

    def get_order(self, order_id):
        return self.real.get_order(order_id)


class EchoPayPal:
    # no PayPal at all: keeps the order body and hands it back on read, which is what the
    # sandbox does for the two calls the verifier makes
    def __init__(self):
        self.lock = threading.Lock()
        self.saved = {}
        self.orders = []

    def create_order(self, body, request_id=None):
        if "payment_source" in body:
            raise RuntimeError("The eval never pays for anything")
        with self.lock:
            order_id = "EVAL-ECHO-" + str(len(self.saved) + 1).zfill(6)
            order = json.loads(json.dumps(body))
            order["id"] = order_id
            order["status"] = "CREATED"
            self.saved[order_id] = order
        return json.loads(json.dumps(order))

    def get_order(self, order_id):
        with self.lock:
            return json.loads(json.dumps(self.saved[order_id]))


# ---- one run of one case ----


def snapshot_store(session, store_id):
    # everything the run left in the database, as plain data
    store = session.get(models.Store, store_id)
    spec, version = shop.latest_spec(session, store_id)
    runs = review.store_runs(session, store_id)
    latest = review.latest_runs(runs)
    rows = review.review_rows(session, store_id)

    attempts = {}
    for run in runs:
        attempts[run.item_id] = max(attempts.get(run.item_id, 0), run.attempt)

    flags = {}
    items = []
    notes = []
    if spec is not None:
        flags = review.compute_flags(spec, review.spec_history(session, store_id), runs)
        notes = list(spec.extraction_notes)
        for item in spec.items:
            run = latest.get(item.id)
            verified = bool(item.available and run is not None and run.ok)
            item_flags = flags.get(item.id) or {}
            row = rows.get(item.id)
            items.append({
                "id": item.id,
                "name": item.name,
                "unit_price": item.unit_price,
                "available": item.available,
                "variants": [variant.model_dump() for variant in item.variants],
                "add_ons": [add_on.model_dump() for add_on in item.add_ons],
                "source_quote": item.source_quote,
                "verified": verified,
                "paypal_order_id": run.paypal_order_id if run is not None else None,
                "last_reason": run.reason if run is not None else None,
                "repairs": attempts.get(item.id, 0),
                "flags": item_flags,
                # what the publish rule does with it: verified and nothing to look at
                "auto_publish": verified and not item_flags,
                "published_in_db": bool(row.published) if row is not None else False,
            })

    return {
        "status": store.status if store is not None else None,
        "error": store.error if store is not None else None,
        "merchant": spec.merchant.model_dump() if spec is not None else None,
        "shipping": spec.shipping.model_dump() if spec is not None else None,
        "spec_versions": version,
        "extraction_notes": notes,
        "items": items,
    }


def run_one(case, url, store_id, settings, session_factory, paypal, ai_factory):
    session = session_factory()
    try:
        session.add(models.Store(
            id=store_id, source_url=url, status=models.CONNECTING, mode="live"
        ))
        session.commit()
    finally:
        session.close()

    started = time.monotonic()
    # the same function the API's background thread runs. it never raises
    run_connect(store_id, url, "live", settings, paypal, session_factory, ai_factory=ai_factory)
    seconds = time.monotonic() - started

    events = bus.history(store_id)
    bus.clear(store_id)
    final_event = events[-1] if events else None

    session = session_factory()
    try:
        snapshot = snapshot_store(session, store_id)
    finally:
        session.close()

    snapshot["store_id"] = store_id
    snapshot["url"] = url
    snapshot["seconds"] = round(seconds, 1)
    snapshot["final_event"] = {
        "type": final_event["type"], "message": final_event["message"],
    } if final_event else None
    return snapshot


# ---- scoring ----


def norm(text):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def contains_name(haystack, candidates):
    # true when one of the candidates shows up in haystack as whole words
    padded = " " + norm(haystack) + " "
    for candidate in candidates:
        wanted = norm(candidate)
        if wanted and " " + wanted + " " in padded:
            return True
    return False


def money(value):
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def match_items(golden_items, spec_items):
    # returns {spec index: (golden index, "match" or "split")} and the golden indexes found.
    # an item the page sells as three (Wool Camp Blanket Small / Medium / Large) is a "split",
    # not an invented one
    matches = {}
    found = set()
    for spec_index, spec_item in enumerate(spec_items):
        best = None
        best_length = -1
        for golden_index, golden_item in enumerate(golden_items):
            candidates = [golden_item["name"]] + list(golden_item.get("aliases") or [])
            if contains_name(spec_item["name"], candidates):
                # the longest golden name wins, so "Half Body" beats a shorter overlap
                length = len(golden_item["name"])
                if length > best_length:
                    best = golden_index
                    best_length = length
        if best is None:
            continue
        if best in found:
            matches[spec_index] = (best, "split")
        else:
            matches[spec_index] = (best, "match")
            found.add(best)
    return matches, found


def label_matches(spec_label, golden_option):
    candidates = [golden_option["label"]] + list(golden_option.get("aliases") or [])
    return contains_name(spec_label, candidates)


def check_options(golden_item, spec_item):
    # variant and add-on prices. returns (expected, correct, wrong, problems). a missing option
    # only costs a sale, so it isn't "wrong". a variant or add-on at a price the store doesn't
    # charge, or one the store doesn't offer, is wrong
    expected = 0
    correct = 0
    wrong = 0
    problems = []
    golden_variants = golden_item.get("variants") or []
    golden_add_ons = golden_item.get("add_ons") or []

    used = set()
    for golden_variant in golden_variants:
        if golden_variant.get("base"):
            continue
        expected += 1
        hit = None
        for index, variant in enumerate(spec_item["variants"]):
            if index not in used and label_matches(variant["label"], golden_variant):
                hit = index
                break
        if hit is None:
            problems.append("variant " + golden_variant["label"] + " missing")
            continue
        used.add(hit)
        got = money(spec_item["variants"][hit]["unit_price"])
        if got == money(golden_variant["unit_price"]):
            correct += 1
        else:
            wrong += 1
            problems.append("variant " + golden_variant["label"] + " is " + str(got)
                            + ", should be " + golden_variant["unit_price"])

    for index, variant in enumerate(spec_item["variants"]):
        if index in used:
            continue
        # the base option repeated as a variant is fine as long as its price is the base price
        base_ok = False
        for golden_variant in golden_variants:
            if golden_variant.get("base") and label_matches(variant["label"], golden_variant):
                base_ok = money(variant["unit_price"]) == money(golden_variant["unit_price"])
        if not base_ok:
            wrong += 1
            problems.append("extra variant " + variant["label"] + " at " + variant["unit_price"])

    used = set()
    for golden_add_on in golden_add_ons:
        expected += 1
        hit = None
        for index, add_on in enumerate(spec_item["add_ons"]):
            if index not in used and label_matches(add_on["label"], golden_add_on):
                hit = index
                break
        if hit is None:
            problems.append("add-on " + golden_add_on["label"] + " missing")
            continue
        used.add(hit)
        got = money(spec_item["add_ons"][hit]["price"])
        if got == money(golden_add_on["price"]):
            correct += 1
        else:
            wrong += 1
            problems.append("add-on " + golden_add_on["label"] + " is " + str(got)
                            + ", should be " + golden_add_on["price"])
    for index, add_on in enumerate(spec_item["add_ons"]):
        if index not in used:
            wrong += 1
            problems.append("extra add-on " + add_on["label"] + " at " + add_on["price"])

    return expected, correct, wrong, problems


def classify_flag(field, golden_item, spec_item, kind, value_wrong):
    # "ambiguous": the golden file says this field is a real judgment call
    # "caught":    the value really is wrong (or the item shouldn't exist), the flag earned its keep
    # "noise":     nothing wrong and nothing tricky
    if kind == "invented":
        return "caught"
    if value_wrong.get(field):
        return "caught"
    # a tricky item counts whichever of its cells the flag sits on: the app files a note like
    # "Small is the base Wool Camp Blanket" under name, and it still points the merchant at
    # the right row
    if golden_item is not None and golden_item.get("tricky_fields"):
        return "ambiguous"
    return "noise"


def score_run(golden, snapshot):
    golden_items = golden.get("items") or []
    spec_items = snapshot["items"]
    forbidden = set()
    for price in golden.get("forbidden_prices") or []:
        forbidden.add(money(price))

    matches, found = match_items(golden_items, spec_items)

    score = {
        "golden_items": len(golden_items),
        "items_found": len(found),
        "spec_items": len(spec_items),
        "invented": 0,
        "splits": 0,
        "verified": 0,
        "verified_price_right": 0,
        "verified_price_checked": 0,
        "options_expected": 0,
        "options_correct": 0,
        "wrong_prices_verified": 0,
        "wrong_prices_auto_published": 0,
        "wrong_prices_caught": 0,
        "flags": {"ambiguous": 0, "caught": 0, "noise": 0},
        "not_for_sale_total": 0,
        "not_for_sale_excluded": 0,
        "repairs": 0,
        "problems": [],
        "flag_details": [],
    }

    for spec_index, spec_item in enumerate(spec_items):
        score["repairs"] += spec_item["repairs"]
        golden_item = None
        kind = "invented"
        if spec_index in matches:
            golden_index, kind = matches[spec_index]
            golden_item = golden_items[golden_index]
        label = spec_item["name"] + " (" + spec_item["unit_price"] + ")"

        price = money(spec_item["unit_price"])
        value_wrong = {}
        option_problems = []
        options_wrong = 0
        if kind == "invented":
            score["invented"] += 1
            score["problems"].append("invented item " + label)
            price_wrong = True
        elif kind == "split":
            score["splits"] += 1
            allowed = {money(golden_item["unit_price"])}
            for variant in golden_item.get("variants") or []:
                allowed.add(money(variant["unit_price"]))
            price_wrong = golden_item["unit_price"] is None or price not in allowed
            value_wrong["unit_price"] = price_wrong
        else:
            golden_price = money(golden_item["unit_price"])
            price_wrong = golden_price is None or price != golden_price
            value_wrong["unit_price"] = price_wrong
            if golden_item["for_sale"] is False:
                value_wrong["available"] = spec_item["available"]
            expected, correct, options_wrong, option_problems = check_options(
                golden_item, spec_item)
            score["options_expected"] += expected
            score["options_correct"] += correct
            for problem in option_problems:
                score["problems"].append(spec_item["name"] + ": " + problem)
            if price_wrong:
                if golden_price is None:
                    score["problems"].append(label + ": the page gives no price for it")
                else:
                    score["problems"].append(label + ": should be " + str(golden_price))

        not_for_sale = golden_item is not None and golden_item["for_sale"] is False
        on_forbidden = price in forbidden
        for variant in spec_item["variants"]:
            if money(variant["unit_price"]) in forbidden:
                on_forbidden = True

        wrong = price_wrong or options_wrong > 0 or not_for_sale or on_forbidden
        if spec_item["verified"]:
            score["verified"] += 1
            if kind == "match" and golden_item["unit_price"] is not None:
                score["verified_price_checked"] += 1
                if not price_wrong:
                    score["verified_price_right"] += 1
            if wrong:
                score["wrong_prices_verified"] += 1
                score["problems"].append("VERIFIED WITH A WRONG PRICE: " + label)
                if spec_item["auto_publish"]:
                    score["wrong_prices_auto_published"] += 1
        elif wrong and spec_item["available"] and kind != "invented":
            # the verifier (or a repair) stopped a wrong price
            score["wrong_prices_caught"] += 1

        for field, reasons in spec_item["flags"].items():
            verdict = classify_flag(field, golden_item, spec_item, kind, value_wrong)
            score["flags"][verdict] += 1
            score["flag_details"].append({
                "item": spec_item["name"], "field": field, "verdict": verdict,
                "reasons": reasons,
            })

    for golden_index, golden_item in enumerate(golden_items):
        if golden_item["for_sale"] is not False:
            continue
        score["not_for_sale_total"] += 1
        excluded = True
        for spec_index, (matched_index, _kind) in matches.items():
            if matched_index != golden_index:
                continue
            spec_item = spec_items[spec_index]
            if spec_item["available"] or spec_item["verified"]:
                excluded = False
        if excluded:
            score["not_for_sale_excluded"] += 1
        else:
            score["problems"].append(golden_item["name"] + " is not for sale but was offered")

    if golden.get("kind") == "negative":
        score["negative"] = judge_negative(golden, snapshot, score)
    return score


def judge_negative(golden, snapshot, score):
    crashed = bool(snapshot["error"] and snapshot["error"].startswith("The connect run crashed"))
    clean_failure = (
        snapshot["status"] == models.FAILED and score["verified"] == 0 and not crashed
    )
    expect = golden["expect"]
    if expect == "rejected":
        passed = clean_failure
    else:
        # real_price_kept: nothing verified at a wrong or forbidden price, and no crash
        passed = score["wrong_prices_verified"] == 0 and not crashed

    if score["verified"] > 0:
        shown = []
        for item in snapshot["items"]:
            if item["verified"]:
                shown.append(item["name"] + " at " + item["unit_price"])
        what = "Verified " + ", ".join(shown)
    else:
        what = "Nothing verified"
    reason = snapshot["error"] or (snapshot["final_event"] or {}).get("message") or ""
    return {
        "expect": expect,
        "passed": passed,
        "clean_failure": clean_failure,
        "crashed": crashed,
        "outcome": what,
        "reason": reason,
    }


# ---- adding runs up ----


def add_up(case_runs):
    total = {
        "runs": len(case_runs),
        "golden_items": 0, "items_found": 0, "invented": 0, "splits": 0, "verified": 0,
        "verified_price_right": 0, "verified_price_checked": 0,
        "options_expected": 0, "options_correct": 0,
        "wrong_prices_verified": 0, "wrong_prices_auto_published": 0, "wrong_prices_caught": 0,
        "flags": {"ambiguous": 0, "caught": 0, "noise": 0},
        "not_for_sale_total": 0, "not_for_sale_excluded": 0, "repairs": 0,
        "seconds": 0.0, "claude_calls": 0, "input_tokens": 0, "output_tokens": 0,
        "negatives_passed": 0, "negatives_total": 0,
    }
    for run in case_runs:
        score = run["score"]
        for key in total:
            if key in ("runs", "flags", "seconds", "claude_calls", "input_tokens",
                       "output_tokens", "negatives_passed", "negatives_total"):
                continue
            total[key] += score[key]
        for verdict in total["flags"]:
            total["flags"][verdict] += score["flags"][verdict]
        total["seconds"] += run["snapshot"]["seconds"]
        total["claude_calls"] += run["claude"]["calls"]
        total["input_tokens"] += run["claude"]["input_tokens"]
        total["output_tokens"] += run["claude"]["output_tokens"]
        if "negative" in score:
            total["negatives_total"] += 1
            if score["negative"]["passed"]:
                total["negatives_passed"] += 1
    total["seconds"] = round(total["seconds"], 1)
    return total


# ---- the report ----


def ratio(right, out_of):
    return str(right) + " of " + str(out_of)


def per_run(value, runs):
    if not runs:
        return "0"
    return str(round(value / runs, 1)).removesuffix(".0")


def markdown_report(results):
    lines = []
    meta = results["meta"]
    lines.append("### Connect")
    lines.append("")
    lines.append(
        "Ran " + meta["run_date"] + " against `" + meta["model"] + "`, "
        + str(meta["runs_per_case"]) + (" run" if meta["runs_per_case"] == 1 else " runs")
        + " per case (Claude isn't deterministic, every number below adds all runs up). "
        + "PayPal: " + meta["paypal_label"] + "."
    )
    if meta.get("note"):
        lines.append("")
        lines.append(meta["note"])
    lines.append("")
    lines.append(
        "| Store | Items found | Invented | Verified prices right | Variant and add-on prices "
        "right | Wrong prices verified | Amber flags (ambiguous / caught a wrong value / noise) "
        "| Not for sale kept out | Time per run | Claude calls, tokens per run |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for case in results["cases"]:
        if case["kind"] != "store":
            continue
        total = case["total"]
        lines.append(store_row(case["case"], total))
    lines.append(store_row("**All stores**", results["overall"]["stores"], bold=True))
    lines.append("")

    lines.append("| Negative case | Should | Passed | What happened (first run) |")
    lines.append("|---|---|---|---|")
    for case in results["cases"]:
        if case["kind"] != "negative":
            continue
        total = case["total"]
        first = case["runs"][0]["score"]["negative"] if case["runs"] else None
        what = ""
        if first:
            what = first["outcome"]
            if first["reason"]:
                what += ". " + first["reason"].rstrip(".") + "."
        lines.append(
            "| " + case["case"] + " | " + SHOULD.get(case["expect"], case["expect"]) + " | "
            + ratio(total["negatives_passed"], total["negatives_total"]) + " | "
            + what.replace("|", "/") + " |"
        )
    lines.append("")

    overall = results["overall"]
    lines.append(
        "**Wrong prices verified: " + str(overall["stores"]["wrong_prices_verified"]
                                          + overall["negatives"]["wrong_prices_verified"])
        + "** across " + str(overall["total_runs"]) + " connect runs. Negative cases passed: "
        + ratio(overall["negatives"]["negatives_passed"], overall["negatives"]["negatives_total"])
        + "."
    )
    orders = results["paypal_orders"]
    if meta["paypal"] == "sandbox":
        lines.append("")
        lines.append(
            str(len(orders)) + " PayPal sandbox orders were created by the verifier's check "
            "(never captured, no payer, they lapse). Every id is in results/latest.json."
        )
    return "\n".join(lines) + "\n"


SHOULD = {
    "rejected": "fail cleanly, nothing verified",
    "real_price_kept": "keep $64, nothing at $1",
}


def store_row(name, total, bold=False):
    runs = total["runs"]
    flags = total["flags"]
    wrong = str(total["wrong_prices_verified"])
    if bold:
        wrong = "**" + wrong + "**"
    tokens = (per_run(total["input_tokens"], runs) + " in / "
              + per_run(total["output_tokens"], runs) + " out")
    return (
        "| " + name
        + " | " + ratio(total["items_found"], total["golden_items"])
        + " | " + str(total["invented"])
        + " | " + ratio(total["verified_price_right"], total["verified_price_checked"])
        + " | " + ratio(total["options_correct"], total["options_expected"])
        + " | " + wrong
        + " | " + str(flags["ambiguous"] + flags["caught"] + flags["noise"]) + " ("
        + str(flags["ambiguous"]) + " / " + str(flags["caught"]) + " / " + str(flags["noise"]) + ")"
        + " | " + ratio(total["not_for_sale_excluded"], total["not_for_sale_total"])
        + " | " + per_run(total["seconds"], runs) + " s"
        + " | " + per_run(total["claude_calls"], runs) + ", " + tokens
        + " |"
    )


# ---- main ----


def build_settings(page_hosts):
    # the app's own settings (.env in the repo root), with three things pinned for the eval
    settings = Settings(_env_file=os.path.join(REPO_ROOT, ".env"))
    allow = []
    for host in page_hosts:
        allow.append(host)
    return settings.model_copy(update={
        "fetch_allow_hosts": ",".join(allow),
        "record_fixtures": False,
        "demo_mode": "live",
    })


def main():
    parser = argparse.ArgumentParser(description="Score Connect against the golden files")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--local", action="store_true",
                       help="run the pipeline in-process on a throwaway database (default)")
    where.add_argument("--api", action="store_true", help="not supported, see the top of the file")
    parser.add_argument("--runs", type=int, default=3, help="runs per case (default 3)")
    parser.add_argument("--cases", nargs="+", help="only these cases (golden file names)")
    parser.add_argument("--paypal", choices=["sandbox", "echo"], default="sandbox",
                        help="sandbox: the verifier's real sandbox check (default). "
                        "echo: no PayPal at all")
    parser.add_argument("--stores-from", choices=["hosted", "repo"], default="hosted",
                        help="read the demo stores from Render (default) or serve the repo copy")
    parser.add_argument("--workers", type=int, default=3, help="connect runs at once (default 3)")
    parser.add_argument("--out", help="where to save the json (the .md goes next to it)")
    parser.add_argument("--keep-db", action="store_true", help="don't delete the eval database")
    parser.add_argument("--note", help="a line to put under the run date in the report")
    args = parser.parse_args()

    if args.api:
        print(API_REFUSAL)
        return 2
    if args.runs < 1:
        print("--runs has to be at least 1")
        return 2

    logging.basicConfig(level=logging.WARNING)

    cases = load_cases()
    if args.cases:
        wanted = set(args.cases)
        cases = [case for case in cases if case["case"] in wanted]
        missing = wanted - {case["case"] for case in cases}
        if missing:
            print("No golden file for: " + ", ".join(sorted(missing)))
            return 2
    full_run = not args.cases

    # local pages: the fixtures always, the demo stores only with --stores-from repo
    servers = []
    fixture_server, fixture_port = start_page_server(FIXTURES_DIR)
    servers.append(fixture_server)
    page_hosts = ["127.0.0.1:" + str(fixture_port)]
    store_base = None
    if args.stores_from == "repo":
        store_server, store_port = start_page_server(DEMO_STORES_DIR)
        servers.append(store_server)
        page_hosts.append("127.0.0.1:" + str(store_port))
        store_base = "http://127.0.0.1:" + str(store_port) + "/"

    settings = build_settings(page_hosts)
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY isn't set (in .env or the environment). "
              "The eval calls Claude live.")
        return 2

    if args.paypal == "sandbox":
        if not settings.paypal_client_id or not settings.paypal_client_secret:
            print("PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET aren't set. "
                  "Set them or use --paypal echo.")
            return 2
        paypal = RecordingPayPal(client_from_settings(settings))
        paypal_label = "sandbox, the verifier's own check (orders created, never captured)"
    else:
        paypal = EchoPayPal()
        paypal_label = "echo stand-in, no PayPal calls"

    db_dir = tempfile.mkdtemp(prefix="connect-evals-")
    engine = make_engine("sqlite:///" + os.path.join(db_dir, "evals.db").replace("\\", "/"))
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    # every (case, run) gets its own store id
    jobs = []
    next_id = EVAL_STORE_ID_BASE + 1
    for case in cases:
        if "fixture" in case:
            url = "http://127.0.0.1:" + str(fixture_port) + "/" + case["fixture"]
        elif store_base is not None and case["kind"] == "store":
            url = store_base + case["case"] + "/"
        else:
            url = case["url"]
        for run_number in range(1, args.runs + 1):
            jobs.append((case, run_number, url, next_id))
            next_id += 1

    print("Connect evals: " + str(len(cases)) + " cases, " + str(args.runs) + " runs each, "
          + str(len(jobs)) + " connect runs, model " + CLAUDE_MODEL + ", PayPal " + args.paypal)

    def do_job(job):
        case, run_number, url, store_id = job
        tally = Tally()
        snapshot = run_one(case, url, store_id, settings, session_factory, paypal,
                           counting_ai_factory(tally))
        score = score_run(case, snapshot)
        line = (case["case"] + " run " + str(run_number) + ": " + str(snapshot["status"])
                + ", " + str(score["verified"]) + " verified, wrong prices verified "
                + str(score["wrong_prices_verified"]) + ", " + str(snapshot["seconds"]) + " s")
        if "negative" in score:
            line += ", " + ("PASS" if score["negative"]["passed"] else "FAIL")
        print(line, flush=True)
        return {
            "run": run_number,
            "claude": {
                "calls": tally.calls,
                "input_tokens": tally.input_tokens,
                "output_tokens": tally.output_tokens,
                "models": sorted(tally.models),
            },
            "snapshot": snapshot,
            "score": score,
        }

    started = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            outcomes = list(pool.map(do_job, jobs))
    finally:
        for server in servers:
            server.shutdown()
        engine.dispose()
        if args.keep_db:
            print("Kept the eval database in " + db_dir)
        else:
            shutil.rmtree(db_dir, ignore_errors=True)
    wall_seconds = round(time.monotonic() - started, 1)

    # put the runs back with their cases
    by_case = {}
    for job, outcome in zip(jobs, outcomes, strict=True):
        by_case.setdefault(job[0]["case"], []).append(outcome)

    case_results = []
    store_runs_all = []
    negative_runs_all = []
    models_seen = set()
    for case in cases:
        runs = by_case.get(case["case"], [])
        for run in runs:
            for model in run["claude"]["models"]:
                models_seen.add(model)
            if case["kind"] == "store":
                store_runs_all.append(run)
            else:
                negative_runs_all.append(run)
        case_results.append({
            "case": case["case"],
            "kind": case["kind"],
            "expect": case.get("expect"),
            "url": runs[0]["snapshot"]["url"] if runs else None,
            "total": add_up(runs),
            "runs": runs,
        })

    meta = {
        "run_date": datetime.now(timezone.utc).strftime("%B %d, %Y").replace(" 0", " "),
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": CLAUDE_MODEL,
        "models_served": sorted(models_seen),
        "runs_per_case": args.runs,
        "paypal": args.paypal,
        "paypal_label": paypal_label,
        "stores_from": args.stores_from,
        "wall_seconds": wall_seconds,
        "eval_store_ids": [EVAL_STORE_ID_BASE + 1, next_id - 1],
        "note": args.note,
    }
    results = {
        "meta": meta,
        "overall": {
            "total_runs": len(jobs),
            "stores": add_up(store_runs_all),
            "negatives": add_up(negative_runs_all),
        },
        "cases": case_results,
        "paypal_orders": paypal.orders,
    }

    report = markdown_report(results)
    print()
    print(report)

    out = args.out
    if out is None and full_run:
        out = os.path.join(RESULTS_DIR, "latest.json")
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
            f.write("\n")
        markdown_path = os.path.splitext(out)[0] + ".md"
        with open(markdown_path, "w", encoding="utf-8") as f:
            f.write(report)
        print("Saved " + out + " and " + markdown_path)
    else:
        print("Partial run, not saved (use --out to save it)")

    overall = results["overall"]
    wrong = (overall["stores"]["wrong_prices_verified"]
             + overall["negatives"]["wrong_prices_verified"])
    return 1 if wrong > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
