# Stand-ins for PayPal and Claude, so the tests never touch a network.
# The specs here are what a correct extraction of each demo store page looks like.

import copy
from pathlib import Path

from backend.app.fetcher import FetchedPage, html_to_text
from backend.app.paypal_client import PayPalError
from backend.app.spec import parse_item, parse_spec

DEMO_STORES_DIR = Path(__file__).resolve().parent.parent.parent / "demo-stores"


def demo_page(slug):
    html = (DEMO_STORES_DIR / slug / "index.html").read_text(encoding="utf-8")
    title, text = html_to_text(html)
    url = "https://demo.example/" + slug + "/"
    return FetchedPage(url=url, final_url=url, title=title, text=text)


def simple_item(item_id, name, price, quote, **extra):
    item = {
        "id": item_id, "name": name, "description": "", "unit_price": price,
        "available": True, "variants": [], "add_ons": [], "source_quote": quote,
    }
    item.update(extra)
    return item


FERNWOOD_SPEC = {
    "spec_version": 1,
    "source_url": "https://demo.example/fernwood-thistle-goods/",
    "merchant": {"name": "Fernwood & Thistle Goods", "currency": "USD"},
    "items": [
        simple_item("waxed-canvas-tote", "Waxed Canvas Tote", "48.00", "Waxed Canvas Tote: $48"),
        simple_item("enamel-camp-mug", "Enamel Camp Mug", "14.00", "Enamel Camp Mug: $14"),
        simple_item("beeswax-pillar-candle", "Beeswax Pillar Candle", "18.00",
                    "Beeswax Pillar Candle: $18"),
        simple_item("linen-tea-towels", "Linen Tea Towels", "22.00",
                    "Linen Tea Towels, set of 2: $22"),
        simple_item(
            "wool-camp-blanket", "Wool Camp Blanket", "85.00", "Wool Camp Blanket, Small: $85",
            variants=[
                {"id": "medium", "label": "Medium", "unit_price": "120.00"},
                {"id": "large", "label": "Large", "unit_price": "160.00"},
            ],
        ),
        simple_item("brass-key-hook", "Brass Key Hook", "12.00", "Brass Key Hook: $12"),
    ],
    "shipping": {"type": "flat", "amount": "6.00", "notes": "Flat per order, US only"},
    "extraction_notes": ["Small is the base Wool Camp Blanket, Medium and Large are variants"],
}

QUILL_SPEC = {
    "spec_version": 1,
    "source_url": "https://demo.example/quill-pipkin-studio/",
    "merchant": {"name": "Quill & Pipkin Studio", "currency": "USD"},
    "items": [
        simple_item(
            "headshot", "Headshot", "40.00", "Headshots are $40",
            add_ons=[{"id": "background", "label": "Background", "price": "15.00"}],
        ),
        simple_item(
            "half-body", "Half Body", "65.00", "half body $65",
            add_ons=[{"id": "background", "label": "Background", "price": "15.00"}],
        ),
        simple_item(
            "full-body", "Full Body", "90.00", "full body $90",
            add_ons=[{"id": "background", "label": "Background", "price": "15.00"}],
        ),
    ],
    "shipping": {"type": "none", "amount": "0.00", "notes": "Files are delivered by email"},
    "extraction_notes": ["Extra character is +50%, a percentage can't be represented, skipped"],
}

HOLLOWBROOK_SPEC = {
    "spec_version": 1,
    "source_url": "https://demo.example/hollowbrook-bakery/",
    "merchant": {"name": "Hollowbrook Bakery", "currency": "USD"},
    "items": [
        simple_item(
            "sourdough-loaf", "Sourdough Loaf", "9.00",
            "Sourdough Loaf 48 hour ferment, crackly crust | $9",
            variants=[{"id": "half", "label": "Half loaf", "unit_price": "5.00"}],
            add_ons=[{"id": "sliced", "label": "Sliced", "price": "1.00"}],
        ),
        simple_item("seeded-rye", "Seeded Rye", "7.00",
                    "Seeded Rye caraway, sunflower, a little honey | ~~$8~~ $7"),
        simple_item("butter-croissant", "Butter Croissant", "4.00", "$4 SOLD OUT",
                    available=False),
        simple_item("cinnamon-morning-bun", "Cinnamon Morning Bun", "4.50",
                    "Cinnamon Morning Bun orange zest, lots of sugar | $4.50"),
        simple_item("olive-focaccia", "Olive Focaccia", "11.00",
                    "Olive Focaccia is $11 a slab this season"),
    ],
    "shipping": {"type": "flat", "amount": "6.00", "notes": "Local delivery only"},
    "extraction_notes": [
        "Butter Croissant is marked SOLD OUT, set available=false",
        "Seeded Rye was $8 crossed out, now $7, used $7",
        "Olive Focaccia's price is only in the footnote",
    ],
}


def spec_copy(data):
    return parse_spec(copy.deepcopy(data))


class FakePayPal:
    # keeps orders in a dict and answers the way the sandbox does for the calls we make
    def __init__(self):
        self.orders = {}
        self.created_bodies = []
        self.request_ids = []
        self.fail_with = None
        # item name -> what PayPal should "hold" instead, to fake a mismatch
        self.rename = {}
        self.capture_status = "COMPLETED"

    def create_order(self, body, request_id=None):
        if self.fail_with is not None:
            raise self.fail_with
        self.created_bodies.append(copy.deepcopy(body))
        self.request_ids.append(request_id)
        order_id = "ORDER" + str(len(self.orders) + 1).zfill(12)
        order = copy.deepcopy(body)
        order["id"] = order_id
        unit = order["purchase_units"][0]
        name = unit["items"][0]["name"]
        if name in self.rename:
            unit["items"][0]["name"] = self.rename[name]
        if "payment_source" in body:
            order["status"] = "COMPLETED"
            unit["payments"] = {"captures": [{
                "id": "CAPTURE" + str(len(self.orders) + 1).zfill(10),
                "status": self.capture_status,
                "amount": {
                    "currency_code": unit["amount"]["currency_code"],
                    "value": unit["amount"]["value"],
                },
            }]}
        else:
            order["status"] = "CREATED"
        self.orders[order_id] = order
        return copy.deepcopy(order)

    def get_order(self, order_id):
        if order_id not in self.orders:
            raise PayPalError(404, name="RESOURCE_NOT_FOUND", message="No such order")
        return copy.deepcopy(self.orders[order_id])


class FakeAI:
    # extract_spec returns the given spec. repair_item answers from a list of
    # (item dict, note) per item id, in order
    def __init__(self, spec_data, repairs=None):
        self.spec_data = spec_data
        self.repairs = repairs or {}
        self.repair_calls = []

    def extract_spec(self, page):
        data = copy.deepcopy(self.spec_data)
        data["source_url"] = page.url
        return parse_spec(data)

    def repair_item(self, item, reason, page_text):
        self.repair_calls.append((item.id, reason))
        waiting = self.repairs.get(item.id) or []
        if not waiting:
            # no better answer: hand the same broken item back
            return item, "No change"
        item_data, note = waiting.pop(0)
        return parse_item(copy.deepcopy(item_data)), note


class MemoryRecorder:
    def __init__(self):
        self.runs = []
        self.specs = []
        self.version = 1

    def save_run(self, item_id, attempt, version, result):
        self.runs.append((item_id, attempt, version, result))

    def save_spec(self, spec, note):
        self.version += 1
        self.specs.append((self.version, note, spec))
        return self.version


# ---- a scripted Claude ----


class Block:
    def __init__(self, **fields):
        for name, value in fields.items():
            setattr(self, name, value)


def text_block(text):
    return Block(type="text", text=text)


def tool_block(name, tool_input, call_id="call-1"):
    return Block(type="tool_use", name=name, input=tool_input, id=call_id)


class Reply:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason


class FakeClaude:
    # client.beta.messages.create(...) answers with the next scripted reply. a reply can be
    # a function of the request, for answers that depend on an earlier tool result
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.beta = self
        self.messages = self

    def create(self, **request):
        self.requests.append(request)
        reply = self.replies.pop(0)
        if callable(reply):
            reply = reply(request)
        return reply
