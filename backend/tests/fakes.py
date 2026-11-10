# Stand-ins for PayPal and Claude, so the tests never touch a network.
# The specs here are what a correct extraction of each demo store page looks like.

import copy
from pathlib import Path

from backend.app.check_client import CheckError
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


# ---- a stand-in for the Check service ----


class FakeCheck:
    # answers the way check/docs/api.md says the real service does. the agent side gets the
    # four-field status object, the merchant side gets the full order
    def __init__(self, can_read=True):
        self.can_read = can_read
        self.mandates = []
        self.orders = {}
        self.sent_orders = []
        self.review_links = []
        # the dashboard login. sessions holds every token handed out
        self.password = "open-sesame"
        self.sessions = []
        self.list_calls = 0
        # what the check decides for the next order: (status, review_state, intent_check)
        self.decide = (
            "captured", "auto_approved",
            {"verdict": "match", "risk_score": 5, "reason": "Matches the mandate."},
        )
        self.fail_mandate = None
        self.fail_order = None
        self.held_total = None
        self.stats = {
            "total_orders": 7, "auto_captured": 3, "needs_review": 1, "approved": 2,
            "voided": 1, "median_decision_ms": 1400, "fast_streak": 3,
            "rubber_stamp_active": True, "fast_threshold_ms": 2000,
            "recent_decision_ms": [900, 1200, 1500],
        }

    def create_mandate(self, request_text, merchant, buyer_label):
        if self.fail_mandate is not None:
            raise self.fail_mandate
        mandate = {
            "id": len(self.mandates) + 1, "raw_request": request_text, "merchant": merchant,
            "buyer_label": buyer_label,
        }
        self.mandates.append(mandate)
        return copy.deepcopy(mandate)

    def create_order(self, mandate_id, items, shipping, vault_id, merchant):
        if self.fail_order is not None:
            raise self.fail_order
        sent = {
            "mandate_id": mandate_id, "items": copy.deepcopy(items), "shipping": shipping,
            "vault_id": vault_id, "merchant": merchant,
        }
        self.sent_orders.append(sent)
        total = 0
        for item in items:
            total += round(float(item["unit_price"]) * item["quantity"] * 100)
        total += round(float(shipping) * 100)
        status, review_state, intent_check = self.decide
        order_id = len(self.orders) + 41
        number = str(order_id).zfill(10)
        order = {
            "id": order_id,
            "mandate_id": mandate_id,
            "status": status,
            "review_state": review_state,
            "total": self.held_total or "%d.%02d" % (total // 100, total % 100),
            "paypal_order_id": "CHECKORDER" + number,
            "authorization_id": "AUTH" + number,
            "capture_id": "CHECKCAPTURE" + number if status == "captured" else None,
            "merchant": merchant,
            "intent_check": copy.deepcopy(intent_check),
            "approval": None,
        }
        self.orders[order_id] = order
        return {"id": order_id, "status": status, "review_state": review_state,
                "total": order["total"]}

    def human_decides(self, order_id, action, decision_ms):
        # what the confirm page does: approve captures, reject voids
        order = self.orders[order_id]
        if action == "approve":
            order["status"] = "captured"
            order["review_state"] = "approved"
            order["capture_id"] = "CHECKCAPTURE" + str(order_id).zfill(10)
        else:
            order["status"] = "voided"
            order["review_state"] = "rejected"
        order["approval"] = {"action": action, "decision_ms": decision_ms}

    def human_accepts_fix(self, order_id, decision_ms, link=True, outcome="captured"):
        # the confirm page's third button: the order is voided and Check places the suggested
        # one itself. link=False is the moment in between, the void saved and the new order
        # not linked yet. returns the new order's id
        order = self.orders[order_id]
        order["status"] = "voided"
        order["review_state"] = "rejected"
        order["approval"] = {"action": "accept_fix", "decision_ms": decision_ms}
        if not link:
            return None
        return self.link_replacement(order_id, outcome)

    def link_replacement(self, order_id, outcome="captured"):
        order = self.orders[order_id]
        new_id = max(self.orders) + 1
        number = str(new_id).zfill(10)
        captured = outcome == "captured"
        self.orders[new_id] = {
            "id": new_id,
            "mandate_id": order["mandate_id"],
            "status": "captured" if captured else "authorized",
            "review_state": "auto_approved" if captured else "needs_review",
            "items": [{"name": "Sourdough Loaf", "size": "Half loaf", "quantity": 1,
                       "unit_price": "5.00"}],
            "total": "11.00",
            "currency": "USD",
            "paypal_order_id": "CHECKORDER" + number,
            "authorization_id": "AUTH" + number,
            "capture_id": "CHECKCAPTURE" + number if captured else None,
            "merchant": order["merchant"],
            "intent_check": {"verdict": "match", "risk_score": 4,
                             "reason": "Matches the mandate."},
            "approval": None,
            "replaces_order_id": order_id,
            "replaced_by_order_id": None,
        }
        order["replaced_by_order_id"] = new_id
        return new_id

    def get_order(self, order_id):
        if order_id not in self.orders:
            raise CheckError("Order " + str(order_id) + " not found", 404)
        return copy.deepcopy(self.orders[order_id])

    def list_orders(self, limit=200):
        self.list_calls += 1
        newest_first = sorted(self.orders.values(), key=lambda order: -order["id"])
        return copy.deepcopy(newest_first[:limit])

    def create_session(self, password):
        if password != self.password:
            raise CheckError("Wrong password", 401)
        token = "session-" + str(len(self.sessions) + 1)
        self.sessions.append(token)
        return {"session_token": token, "expires_at": "2026-12-03T09:56:55Z"}

    def create_review_link(self, order_id, session_token):
        if session_token not in self.sessions:
            raise CheckError("Missing or wrong API key", 401)
        order = self.get_order(order_id)
        if order["review_state"] != "needs_review":
            raise CheckError("This order isn't waiting for review", 409)
        token = "token-" + str(order_id) + "-" + str(len(self.review_links) + 1)
        self.review_links.append(token)
        return {"review_token": token, "expires_at": "2026-12-03T01:56:55Z"}

    def get_stats(self):
        # the shape of Check's GET /stats, with the extra numbers the route should drop
        return copy.deepcopy(self.stats)

    def list_disputes(self, limit=200):
        return [{"id": 3, "paypal_dispute_id": "PP-R-ABC-10001234", "order_id": 41,
                 "reason": "UNAUTHORISED", "status": "WAITING_FOR_SELLER_RESPONSE",
                 "evidence_submitted": False, "has_summary": False}]

    def sync_disputes(self):
        return {"orders_checked": 1, "disputes_found": 1, "created": 1, "updated": 0,
                "errors": []}

    def dispute_evidence(self, dispute_id):
        if dispute_id != 3:
            raise CheckError("Dispute " + str(dispute_id) + " not found", 404)
        return {"dispute": self.list_disputes()[0], "packet": {}, "summary": "The buyer asked."}

    def redraft_dispute(self, dispute_id):
        return self.dispute_evidence(dispute_id)

    def submit_dispute_evidence(self, dispute_id):
        raise CheckError("Evidence was already submitted", 409)
