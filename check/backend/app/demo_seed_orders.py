# The orders Reset demo places, after it has wiped the old ones. Plain data and no imports on
# purpose: the Checkout Anything app's tests read this file on its own and check every price and
# variant here against the recorded store fixtures (backend/tests/test_demo_seed_prices.py in the
# repo root), so a price can't drift away from what the stores really sell.
#
# Every one goes through the real path: the agent's API key, POST /mandates and POST /orders,
# a real hold in the PayPal sandbox, the intent check, then auto-capture or a hold. The held ones
# are then approved or rejected by the seed itself, recorded as decided_by "demo seed".
#
# The items are written the way Checkout Anything's backend sends them to Check (check_items in
# backend/app/orders.py at the repo root): the item name with any add-ons in it, and the variant in
# "size". "catalog" says which fixture item it is, for that test.
#
#   agent      the name its key has in AGENT_API_KEYS. it never says who it is itself, the key does
#   store      the store the human asked for. it goes on the mandate
#   order_at   the store the order was really placed at, when it isn't that one
#   expected   where Check should land it on its own
#   decide     what the seed does with it once it's held

CHECKOUT_ANYTHING = "Checkout Anything"
ERRAND_RUNNER = "Errand Runner"
SEED_AGENTS = [CHECKOUT_ANYTHING, ERRAND_RUNNER]

FERNWOOD = "Fernwood & Thistle Goods"
HOLLOWBROOK = "Hollowbrook Bakery"

AUTO_APPROVED = "auto_approved"
NEEDS_REVIEW = "needs_review"

# flat shipping at both stores, from their pages
SHIPPING = "6.00"

SEED_ORDERS = [
    # ---- clean: these should capture on their own ----
    {
        "name": "clean: enamel camp mug",
        "agent": CHECKOUT_ANYTHING,
        "store": FERNWOOD,
        "request": "Get me one Enamel Camp Mug from Fernwood & Thistle Goods. "
        "Keep it under $25 with shipping.",
        "items": [{"name": "Enamel Camp Mug", "quantity": 1, "unit_price": "14.00"}],
        "catalog": {"store": "fernwood-thistle-goods", "item_id": "enamel-camp-mug"},
        "expected": AUTO_APPROVED,
    },
    {
        "name": "clean: half sourdough, sliced",
        "agent": ERRAND_RUNNER,
        "store": HOLLOWBROOK,
        "request": "A half sourdough loaf from Hollowbrook Bakery, sliced please. "
        "No more than $15 delivered.",
        "items": [{"name": "Sourdough Loaf + Sliced", "size": "Half loaf", "quantity": 1,
                   "unit_price": "6.00"}],
        "catalog": {"store": "hollowbrook-bakery", "item_id": "sourdough-loaf",
                    "variant_id": "half-loaf", "add_on_ids": ["sliced"]},
        "expected": AUTO_APPROVED,
    },
    {
        "name": "clean: beeswax candle",
        "agent": CHECKOUT_ANYTHING,
        "store": FERNWOOD,
        "request": "One Beeswax Pillar Candle from Fernwood & Thistle Goods, up to $30.",
        "items": [{"name": "Beeswax Pillar Candle", "quantity": 1, "unit_price": "18.00"}],
        "catalog": {"store": "fernwood-thistle-goods", "item_id": "beeswax-pillar-candle"},
        "expected": AUTO_APPROVED,
    },
    {
        "name": "clean: linen tea towels",
        "agent": ERRAND_RUNNER,
        "store": FERNWOOD,
        "request": "The linen tea towels from Fernwood & Thistle Goods, one set of two, "
        "under $35.",
        "items": [{"name": "Linen Tea Towels, set of 2", "quantity": 1, "unit_price": "22.00"}],
        "catalog": {"store": "fernwood-thistle-goods", "item_id": "linen-tea-towels"},
        "expected": AUTO_APPROVED,
    },
    {
        "name": "clean: olive focaccia",
        "agent": CHECKOUT_ANYTHING,
        "store": HOLLOWBROOK,
        "request": "Pick up an Olive Focaccia from Hollowbrook Bakery, up to $20.",
        "items": [{"name": "Olive Focaccia", "quantity": 1, "unit_price": "11.00"}],
        "catalog": {"store": "hollowbrook-bakery", "item_id": "olive-focaccia"},
        "expected": AUTO_APPROVED,
    },
    {
        "name": "clean: two brass key hooks",
        "agent": ERRAND_RUNNER,
        "store": FERNWOOD,
        "request": "Two Brass Key Hooks from Fernwood & Thistle Goods, $35 max.",
        "items": [{"name": "Brass Key Hook", "quantity": 2, "unit_price": "12.00"}],
        "catalog": {"store": "fernwood-thistle-goods", "item_id": "brass-key-hook"},
        "expected": AUTO_APPROVED,
    },
    {
        "name": "clean: seeded rye",
        "agent": CHECKOUT_ANYTHING,
        "store": HOLLOWBROOK,
        "request": "One Seeded Rye loaf from Hollowbrook Bakery, under $15.",
        "items": [{"name": "Seeded Rye", "quantity": 1, "unit_price": "7.00"}],
        "catalog": {"store": "hollowbrook-bakery", "item_id": "seeded-rye"},
        "expected": AUTO_APPROVED,
    },
    # ---- held, then decided by the seed. "sneaky:" keeps them off the /place-order default ----
    {
        # asked for the Small, got the Medium. under the cap, so only the size is off
        "name": "sneaky: small blanket, got medium",
        "agent": CHECKOUT_ANYTHING,
        "store": FERNWOOD,
        "request": "A small Wool Camp Blanket from Fernwood & Thistle Goods, up to $130.",
        "items": [{"name": "Wool Camp Blanket", "size": "Medium", "quantity": 1,
                   "unit_price": "120.00"}],
        "catalog": {"store": "fernwood-thistle-goods", "item_id": "wool-camp-blanket",
                    "variant_id": "medium"},
        "expected": NEEDS_REVIEW,
        "decide": "approve",
    },
    {
        # asked for half a loaf, got the whole one
        "name": "sneaky: half loaf, got whole",
        "agent": ERRAND_RUNNER,
        "store": HOLLOWBROOK,
        "request": "Half a sourdough loaf from Hollowbrook Bakery, up to $15.",
        "items": [{"name": "Sourdough Loaf", "quantity": 1, "unit_price": "9.00"}],
        "catalog": {"store": "hollowbrook-bakery", "item_id": "sourdough-loaf"},
        "expected": NEEDS_REVIEW,
        "decide": "approve",
    },
    {
        # the right tote at the right price, sent to the wrong shop. the store rule catches it
        "name": "sneaky: tote at the wrong store",
        "agent": ERRAND_RUNNER,
        "store": FERNWOOD,
        "order_at": HOLLOWBROOK,
        "request": "A Waxed Canvas Tote from Fernwood & Thistle Goods, up to $60.",
        "items": [{"name": "Waxed Canvas Tote", "quantity": 1, "unit_price": "48.00"}],
        "catalog": {"store": "fernwood-thistle-goods", "item_id": "waxed-canvas-tote"},
        "expected": NEEDS_REVIEW,
        "decide": "reject",
    },
]
