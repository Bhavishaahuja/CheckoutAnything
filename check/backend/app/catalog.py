# The demo store's catalog: the products Fernwood Supply Co sells, one row per variant.
# The rows themselves come from the migration (b91d6e2f4a73), this is how the app reads them.
#
# The demo scenarios use it to pick a believable wrong variant: a size the store really stocks,
# the other earbud model at the same price, the same event on another day. Picking from what's
# for sale is what makes the wrong order look like something a real agent would do.

import re
from datetime import date

from decimal import Decimal

from sqlalchemy import select

from backend.app.intent.rules import normalize_merchant
from backend.app.models import CatalogItem
from backend.app.store_catalogs import STORE_CATALOGS

# the parser is told to use exactly these as a mandate's category when the request fits one,
# which is how a mandate finds its rows here. see prompts/mandate.py
CATEGORIES = ["sneakers", "groceries", "electronics", "event tickets", "subscription"]

NUMBER_IN_SIZE = re.compile(r"\d+(?:\.\d+)?")

# sizes in words, smallest first. "S" and "Small" are the same size
WORD_SIZE_RANKS = {
    "xs": 0, "x-small": 0, "extra small": 0, "extra-small": 0,
    "s": 1, "small": 1,
    "m": 2, "medium": 2,
    "l": 3, "large": 3,
    "xl": 4, "x-large": 4, "extra large": 4, "extra-large": 4,
}


def normalize_category(category):
    if not category:
        return None
    return " ".join(category.casefold().split())


def load_category(session, category):
    # every row in the mandate's category, in a fixed order so the same mandate always gets the
    # same wrong variant. empty when the category isn't one the store sells
    wanted = normalize_category(category)
    if wanted not in CATEGORIES:
        return []
    query = select(CatalogItem).where(CatalogItem.category == wanted).order_by(CatalogItem.id)
    return list(session.scalars(query).all())


# ---- picking a sibling variant ----
# these take plain rows and return a value or None, no database. demo.py says what None means


def other_size(rows, wanted_size):
    # the stocked size closest to the one asked for: 9 gets 8.5, not 8. closer is sneakier.
    # keeps whatever came with the number, so "men's 9" turns into "men's 8.5"
    wanted_number = size_number(wanted_size)
    if wanted_number is None:
        return None

    best_size = None
    best_gap = None
    for row in rows:
        number = size_number(row.size)
        if number is None or number == wanted_number:
            continue
        gap = abs(number - wanted_number)
        if best_gap is None or gap < best_gap:
            best_gap = gap
            best_size = row.size
    if best_size is None:
        return None
    return NUMBER_IN_SIZE.sub(best_size, wanted_size, count=1)


def size_number(size):
    if not size:
        return None
    found = NUMBER_IN_SIZE.search(size)
    if found is None:
        return None
    return float(found.group(0))


# ---- the sizes an item really comes in, and what each one costs ----
# the item lives in one of two places: a Connect store's catalog (store_catalogs.py) when the
# mandate names one of those stores, or Check's own catalog_items for the old categories.
# either way it comes out as a list of {"label", "unit_price", "available"}, empty when we don't
# know the item


def item_sizes(merchant, item_name, rules, catalog_rows):
    store_item = find_store_item(merchant, item_name)
    if store_item is not None:
        sizes = []
        for size in store_item["sizes"]:
            sizes.append({
                "label": size["label"],
                "unit_price": Decimal(size["unit_price"]),
                "available": store_item["available"],
            })
        return sizes

    # Check's catalog has a row per variant. keep the rows for this product in the color, model
    # and date the mandate asked for, the size is the one thing left to vary
    wanted_color = (rules.get("color") or "").strip().casefold()
    wanted_model = (rules.get("model") or "").strip().casefold()
    wanted_date = parse_event_date(rules.get("event_date"))
    sizes = []
    for row in catalog_rows:
        if not same_product(row.name, item_name):
            continue
        if wanted_color and row.color and row.color.casefold() != wanted_color:
            continue
        if wanted_model and row.model and row.model.casefold() != wanted_model:
            continue
        if wanted_date is not None and row.event_date and row.event_date != wanted_date:
            continue
        sizes.append({
            "label": row.size,
            "unit_price": Decimal(str(row.price)),
            "available": row.in_stock,
        })
    return sizes


def find_store_item(merchant, item_name):
    # only when the mandate names the store. the same blanket at "any store" has no price we know
    wanted_store = normalize_merchant(merchant)
    if not wanted_store or not item_name:
        return None
    for store in STORE_CATALOGS:
        if normalize_merchant(store["store"]) != wanted_store:
            continue
        # the exact name first, so "Sourdough Loaf" can't land on some other loaf
        for item in store["items"]:
            if item["name"].casefold() == item_name.strip().casefold():
                return item
        for item in store["items"]:
            if same_product(item["name"], item_name):
                return item
    return None


def price_of_size(sizes, wanted_size):
    # the real price of the size the mandate asked for, None when we can't tell which one that is
    if not sizes:
        return None

    # one price for every size (sneakers, a mug), so the size doesn't matter
    first_price = sizes[0]["unit_price"]
    one_price = True
    for size in sizes:
        if size["unit_price"] != first_price:
            one_price = False
    if one_price:
        return first_price

    if not wanted_size or not str(wanted_size).strip():
        # no size named means the item as listed, which is the first size on the page
        return first_price
    for size in sizes:
        if same_size(size["label"], wanted_size):
            return size["unit_price"]
    return None


def same_size(label, wanted_size):
    if not label or not wanted_size:
        return False
    if clean_size(label) == clean_size(wanted_size):
        return True
    label_rank = word_size_rank(label)
    if label_rank is not None and label_rank == word_size_rank(wanted_size):
        return True
    label_number = size_number(label)
    return label_number is not None and label_number == size_number(wanted_size)


def clean_size(size):
    # "Size M " and "m" are both "m"
    text = " ".join(str(size).casefold().split())
    if text.startswith("size "):
        text = text[len("size "):]
    return text


def word_size_rank(size):
    # where a word size sits from XS to XL. None for "9", "64 oz" or "Half loaf"
    if not size:
        return None
    return WORD_SIZE_RANKS.get(clean_size(size))


def next_word_size(sizes, wanted_size):
    # the next size up that the store really has. the biggest one gets the next size down, so a
    # Large blanket still has a wrong size to send
    wanted_rank = word_size_rank(wanted_size)
    if wanted_rank is None:
        return None

    next_up = None
    next_down = None
    for size in sizes:
        if not size["available"]:
            continue
        rank = word_size_rank(size["label"])
        if rank is None or rank == wanted_rank:
            continue
        if rank > wanted_rank:
            if next_up is None or rank < word_size_rank(next_up["label"]):
                next_up = size
        else:
            if next_down is None or rank > word_size_rank(next_down["label"]):
                next_down = size
    if next_up is not None:
        return next_up
    return next_down


def substitute_for(rows, wanted_item):
    # something else in the same category that's actually in stock, which is what an agent
    # reaches for when the real thing is sold out
    for row in rows:
        if row.in_stock and not same_product(row.name, wanted_item):
            return row
    return None


def same_product(catalog_name, wanted_item):
    # same product when every word of the shorter name is in the longer one. "oat milk" and
    # "canvas sneakers" are "Organic oat milk" and "Canvas low-top sneaker". "organic oat milk"
    # isn't "Organic almond milk", oat is missing. a plain substring check got the sneakers wrong
    # and "substituted" the very thing the shopper asked for
    catalog_words = product_words(catalog_name)
    wanted_words = product_words(wanted_item)
    if not catalog_words or not wanted_words:
        return False
    return catalog_words <= wanted_words or wanted_words <= catalog_words


def product_words(name):
    # lowercase words, singular, without the punctuation around them
    words = set()
    for word in re.findall(r"[a-z0-9][a-z0-9'-]*", name.casefold()):
        # "sneakers" and "sneaker" are the same word here. "glass" stays "glass"
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.add(word)
    return words


def other_model(rows, wanted_model):
    # another model at the same price as the one asked for, so the total gives nothing away.
    # if the store doesn't sell the one asked for, any other model will do
    wanted = wanted_model.strip().casefold()
    wanted_price = None
    for row in rows:
        if row.model and row.model.casefold() == wanted:
            wanted_price = row.price

    fallback = None
    for row in rows:
        if not row.model or row.model.casefold() == wanted:
            continue
        if wanted_price is None or row.price == wanted_price:
            return row.model
        if fallback is None:
            fallback = row.model
    return fallback


def other_event_date(rows, wanted_date):
    # the same event on the nearest other day the store has tickets for
    best_date = None
    for row in rows:
        if row.event_date is None or row.event_date == wanted_date:
            continue
        gap = abs((row.event_date - wanted_date).days)
        if best_date is None or gap < abs((best_date - wanted_date).days):
            best_date = row.event_date
    return best_date


def format_event_date(event_date):
    # "Dec 5, 2026". built by hand because %-d doesn't exist on Windows. lives here so fixes.py
    # and orders.py both get it without importing each other
    return event_date.strftime("%b") + " " + str(event_date.day) + ", " + str(event_date.year)


def parse_event_date(value):
    # the parser writes "2026-12-05". anything else isn't a date we can move by a day
    if isinstance(value, date):
        return value
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None
