# The Connect demo stores' catalogs, as Checkout Anything reads them off the store pages. Check is
# a separate service with its own database and never sees Connect's, so /place-order prices orders
# for these stores from here: the real price of the size asked for, and the real price of the
# next size over for a wrong size.
#
# Plain data and no imports on purpose, like demo_seed_orders.py: the Checkout Anything app's
# tests read this file on its own and check every item, size and price here against the recorded
# store fixtures (backend/tests/test_demo_seed_state.py in the repo root), so this can't drift
# away from what the stores really sell.
#
# Every item lists its sizes, the first one at the item's own price and the rest from its
# variants. The store pages don't name the first size anywhere but the price line ("Wool Camp
# Blanket, Small: $85"), so it's written out here. An item that only comes one way has one size
# with no label.
#
#   store       the store's name, the way a Connect mandate names it in "merchant"
#   slug        the fixture it's checked against
#   item_id     the item's id in that fixture
#   available   false when the store marks it sold out

STORE_CATALOGS = [
    {
        "store": "Fernwood & Thistle Goods",
        "slug": "fernwood-thistle-goods",
        "items": [
            {"item_id": "waxed-canvas-tote", "name": "Waxed Canvas Tote", "available": True,
             "sizes": [{"label": None, "unit_price": "48.00"}]},
            {"item_id": "enamel-camp-mug", "name": "Enamel Camp Mug", "available": True,
             "sizes": [{"label": None, "unit_price": "14.00"}]},
            {"item_id": "beeswax-pillar-candle", "name": "Beeswax Pillar Candle",
             "available": True, "sizes": [{"label": None, "unit_price": "18.00"}]},
            {"item_id": "linen-tea-towels", "name": "Linen Tea Towels, set of 2",
             "available": True, "sizes": [{"label": None, "unit_price": "22.00"}]},
            {"item_id": "wool-camp-blanket", "name": "Wool Camp Blanket", "available": True,
             "sizes": [
                 {"label": "Small", "unit_price": "85.00"},
                 {"label": "Medium", "unit_price": "120.00"},
                 {"label": "Large", "unit_price": "160.00"},
             ]},
            {"item_id": "brass-key-hook", "name": "Brass Key Hook", "available": True,
             "sizes": [{"label": None, "unit_price": "12.00"}]},
        ],
    },
    {
        "store": "Hollowbrook Bakery",
        "slug": "hollowbrook-bakery",
        "items": [
            {"item_id": "sourdough-loaf", "name": "Sourdough Loaf", "available": True,
             "sizes": [
                 {"label": None, "unit_price": "9.00"},
                 {"label": "Half loaf", "unit_price": "5.00"},
             ]},
            {"item_id": "seeded-rye", "name": "Seeded Rye", "available": True,
             "sizes": [{"label": None, "unit_price": "7.00"}]},
            {"item_id": "butter-croissant", "name": "Butter Croissant", "available": False,
             "sizes": [{"label": None, "unit_price": "4.00"}]},
            {"item_id": "cinnamon-morning-bun", "name": "Cinnamon Morning Bun",
             "available": True, "sizes": [{"label": None, "unit_price": "4.50"}]},
            {"item_id": "olive-focaccia", "name": "Olive Focaccia", "available": True,
             "sizes": [{"label": None, "unit_price": "11.00"}]},
        ],
    },
    {
        "store": "Quill & Pipkin Studio",
        "slug": "quill-pipkin-studio",
        "items": [
            {"item_id": "character-illustration", "name": "Character illustration",
             "available": True,
             "sizes": [
                 {"label": "Headshot", "unit_price": "40.00"},
                 {"label": "Half body", "unit_price": "65.00"},
                 {"label": "Full body", "unit_price": "90.00"},
             ]},
        ],
    },
]
