# The merchant's review of a connected store: the human in the loop on the catalog side.
#
#   flags      fields the agent was unsure about, each with the reason. Worked out here in
#              fixed code from what the run already recorded (failed checks, repairs, crossed-out
#              prices, Claude's own extraction notes). Claude is never asked how sure it is.
#   resolve    the merchant confirms a flagged field, or corrects it
#   edits      name, description and price go into a new spec version. A new name or price is
#              checked with a real PayPal order before it is saved, same fixed code as the run
#   publish    only published items can be bought. Clean verified items start published,
#              flagged ones wait until every flag on them is resolved
#   order      where each item sits in the catalog an agent reads
#   labels     catalog columns the merchant renamed

import json
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from backend.app import models
from backend.app.demo import slug_for_url
from backend.app.models import ColumnLabel, ItemReview, StoreSpecRow, VerificationRun
from backend.app.spec import SpecError, parse_item, parse_spec, spec_to_json
from backend.app.verifier import PRICE_REGEX, STRUCK_REGEX, paypal_check

# the spec fields a flag can sit on
FLAG_FIELDS = ("name", "unit_price", "available")

CATEGORIES = [
    "Apparel",
    "Accessories",
    "Home",
    "Stationery",
    "Food and drink",
    "Art and prints",
    "Services",
    "Other",
]

# demo stores whose verified items all go live as soon as they connect, flagged ones included,
# so the agent's starter prompts work right after Reset demo. the flags on them count as
# looked at. the other demo stores keep their flags, they're the ones the review is shown on
PUBLISHED_ON_CONNECT = {"hollowbrook-bakery"}

MAX_STOCK = 1_000_000
MAX_LABEL_LENGTH = 40

# every catalog column the merchant can rename: its default label, and where the value goes in
# the PayPal order (None when it stays on our side)
COLUMNS = {
    "name": ("Item", "purchase_units[0].items[0].name"),
    "category": ("Category", None),
    "description": ("Description", None),
    "unit_price": ("Price", "purchase_units[0].items[0].unit_amount.value"),
    "stock": ("Stock", None),
    "published": ("Live on PayPal", None),
    "checked_at": ("Checked", None),
    "paypal_order_id": ("PayPal order", "id"),
    "status": ("Status", None),
}


class ReviewError(Exception):
    def __init__(self, message, status_code=400, extra=None):
        super().__init__(message)
        self.status_code = status_code
        self.extra = extra or {}


# ---- flags ----


def show_money(amount, currency):
    text = str(Decimal(amount).quantize(Decimal("0.01")))
    if currency == "USD":
        return "$" + text
    return text + " " + currency


def struck_prices(text):
    # prices that are crossed out in a quote, "~~$8~~ $7" -> [8]
    prices = []
    for struck in STRUCK_REGEX.findall(text):
        for match in PRICE_REGEX.finditer(struck):
            digits = (match.group(1) or match.group(2)).replace(",", "")
            try:
                prices.append(Decimal(digits))
            except InvalidOperation:
                continue
    return prices


def note_field(note):
    # which cell an extraction note is about
    lowered = note.casefold()
    for word in ("sold out", "unavailable", "not for sale", "available"):
        if word in lowered:
            return "available"
    if PRICE_REGEX.search(note):
        return "unit_price"
    for word in ("price", "cost", "footnote", "crossed"):
        if word in lowered:
            return "unit_price"
    return "name"


def spec_history(session, store_id):
    # every spec version, oldest first, as (version, note, dict)
    rows = session.execute(
        select(StoreSpecRow).where(StoreSpecRow.store_id == store_id).order_by(StoreSpecRow.version)
    ).scalars()
    return [(row.version, row.note, json.loads(row.spec_json)) for row in rows]


def find_in(spec_data, item_id):
    for item in spec_data["items"]:
        if item["id"] == item_id:
            return item
    return None


def compute_flags(spec, history, runs):
    # item id -> {field: [reasons]}. Only from what was recorded, nothing is guessed here
    currency = spec.merchant.currency
    flags = {}

    def add(item_id, field, reason):
        fields = flags.setdefault(item_id, {})
        reasons = fields.setdefault(field, [])
        if reason not in reasons:
            reasons.append(reason)

    runs_by_item = {}
    for run in runs:
        runs_by_item.setdefault(run.item_id, []).append(run)

    for item in spec.items:
        item_runs = runs_by_item.get(item.id, [])

        # 1. Claude had to repair it
        repairs = max((run.attempt for run in item_runs), default=0)
        if repairs > 0:
            first_failure = None
            for run in item_runs:
                if not run.ok and run.reason:
                    first_failure = run.reason
                    break
            first = None
            for _version, _note, data in history:
                first = find_in(data, item.id)
                if first is not None:
                    break
            # what the item looked like after the last repair, before any merchant edit
            repaired = None
            for _version, note, data in history:
                if note.startswith("Merchant edit"):
                    continue
                found = find_in(data, item.id)
                if found is not None:
                    repaired = found
            why = (" after a check failed: " + first_failure) if first_failure else ""
            times = "1 repair" if repairs == 1 else str(repairs) + " repairs"
            if first and repaired and first["unit_price"] != repaired["unit_price"]:
                add(item.id, "unit_price",
                    "Claude first read " + show_money(first["unit_price"], currency)
                    + ", then repaired it to " + show_money(repaired["unit_price"], currency)
                    + why + ".")
            elif first and repaired and first["name"] != repaired["name"]:
                add(item.id, "name",
                    'Claude first called this "' + first["name"] + '", then renamed it' + why
                    + ".")
            else:
                add(item.id, "unit_price", "It took " + times + " to pass the checks" + why + ".")

        # 2. a crossed-out price sits next to the real one
        struck = sorted(set(struck_prices(item.source_quote)))
        if struck:
            shown = " and ".join(show_money(price, currency) for price in struck)
            add(item.id, "unit_price",
                "The page shows " + str(len(struck) + 1) + " prices here: " + shown
                + " crossed out, and " + show_money(item.unit_price, currency)
                + ". Claude used " + show_money(item.unit_price, currency) + ".")

        # 3. Claude wrote a note about it
        for note in spec.extraction_notes:
            if note.startswith("Repair "):
                continue  # covered by 1
            if item.name.casefold() in note.casefold():
                add(item.id, note_field(note), "Claude's note: " + note)

    return flags


# ---- rows ----


def resolved_map(row):
    try:
        found = json.loads(row.resolved_fields or "{}")
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def resolved_set(row):
    return set(resolved_map(row))


def review_rows(session, store_id):
    rows = session.execute(
        select(ItemReview).where(ItemReview.store_id == store_id)
        .order_by(ItemReview.position, ItemReview.id)
    ).scalars()
    return {row.item_id: row for row in rows}


def store_runs(session, store_id):
    return list(session.execute(
        select(VerificationRun).where(VerificationRun.store_id == store_id)
        .order_by(VerificationRun.id)
    ).scalars())


def latest_runs(runs):
    latest = {}
    for run in runs:
        latest[run.item_id] = run
    return latest


def ensure_reviews(session, store, spec):
    # makes the missing review rows. Safe to call on every read: a store connected before this
    # table existed gets its rows the first time anyone looks
    rows = review_rows(session, store.id)
    missing = [item for item in spec.items if item.id not in rows]
    if not missing or store.status == models.CONNECTING:
        return rows

    runs = store_runs(session, store.id)
    flags = compute_flags(spec, spec_history(session, store.id), runs)
    latest = latest_runs(runs)
    publish_all = slug_for_url(store.source_url or "") in PUBLISHED_ON_CONNECT
    position = max((row.position for row in rows.values()), default=-1) + 1
    for item in missing:
        run = latest.get(item.id)
        verified = item.available and run is not None and run.ok
        item_flags = flags.get(item.id) or {}
        # nothing to look at means it can go live on its own
        published = verified and not item_flags
        resolved = {}
        if publish_all and verified:
            # a demo store that goes live whole: its flags are marked as looked at, so the
            # publish rule (every flag resolved) holds for it too
            for field in item_flags:
                resolved[field] = {"by": "demo"}
            published = True
        session.add(ItemReview(
            store_id=store.id,
            item_id=item.id,
            position=position,
            published=published,
            resolved_fields=json.dumps(resolved, sort_keys=True),
        ))
        position += 1
    try:
        session.commit()
    except IntegrityError:
        # another request made the same rows a moment ago
        session.rollback()
    return review_rows(session, store.id)


def open_flags(flags, row):
    # the flagged fields the merchant hasn't dealt with yet
    resolved = resolved_set(row) if row is not None else set()
    return [field for field in flags if field not in resolved]


def labels_for(session, store_id):
    labels = {field: default for field, (default, _paypal) in COLUMNS.items()}
    rows = session.execute(
        select(ColumnLabel).where(ColumnLabel.store_id == store_id)
    ).scalars()
    for row in rows:
        if row.field in labels:
            labels[row.field] = row.label
    return labels


def blocked_reason(item, run, flags, row):
    # why this item can't be published right now, or None
    if not item.available:
        return item.name + " is not for sale on the page"
    if run is None or not run.ok:
        return item.name + " hasn't passed verification"
    waiting = open_flags(flags, row)
    if waiting:
        count = len(waiting)
        return item.name + " has " + str(count) + (" field" if count == 1 else " fields") + \
            " that still " + ("needs" if count == 1 else "need") + " a look"
    return None


def review_payload(session, store, spec):
    rows = ensure_reviews(session, store, spec)
    runs = store_runs(session, store.id)
    flags = compute_flags(spec, spec_history(session, store.id), runs)
    latest = latest_runs(runs)
    labels = labels_for(session, store.id)

    needs_look = 0
    items = []
    for index, item in enumerate(spec.items):
        row = rows.get(item.id)
        item_flags = flags.get(item.id, {})
        resolved = resolved_set(row) if row is not None else set()
        shown = []
        for field in FLAG_FIELDS:
            if field in item_flags:
                is_resolved = field in resolved
                if not is_resolved:
                    needs_look += 1
                shown.append({
                    "field": field, "reasons": item_flags[field], "resolved": is_resolved,
                })
        run = latest.get(item.id)
        items.append({
            "item_id": item.id,
            "position": row.position if row is not None else index,
            "category": row.category if row is not None else None,
            "stock": row.stock if row is not None else None,
            "published": bool(row.published) if row is not None else False,
            "blocked_reason": blocked_reason(item, run, item_flags, row),
            "flags": shown,
            "checked_at": run.created_at.isoformat() if run and run.created_at else None,
        })
    items.sort(key=lambda entry: entry["position"])

    columns = []
    for field, (default, paypal_field) in COLUMNS.items():
        columns.append({
            "field": field, "label": labels[field], "default_label": default,
            "paypal_field": paypal_field,
        })
    return {
        "store_id": store.id,
        "editable": store.status != models.CONNECTING,
        "categories": CATEGORIES,
        "columns": columns,
        "needs_look": needs_look,
        "items": items,
    }


# ---- changes ----


def clean_price(raw):
    # "29", "29.5" and "$29.50" all become "29.50". anything else is refused
    text = str(raw).strip().replace(",", "")
    if text.startswith("$"):
        text = text[1:].strip()
    if not text:
        raise ReviewError("A price can't be blank", 422)
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ReviewError('"' + str(raw).strip() + '" is not a price', 422) from None
    if not value.is_finite():
        raise ReviewError('"' + str(raw).strip() + '" is not a price', 422)
    if value <= 0:
        raise ReviewError("A price has to be above 0.00", 422)
    if value != value.quantize(Decimal("0.01")):
        raise ReviewError("A price can have 2 decimals at most", 422)
    return str(value.quantize(Decimal("0.01")))


def page_backed_price(history, runs, item_id):
    # the last price of this item that passed the page check, or None
    by_version = {version: data for version, _note, data in history}
    price = None
    for run in runs:
        if run.item_id != item_id or not run.page_check_ok:
            continue
        found = find_in(by_version.get(run.spec_version, {"items": []}), item_id)
        if found is not None:
            price = found["unit_price"]
    return price


def require_editable(store):
    if store.status == models.CONNECTING:
        raise ReviewError("This store is still connecting, wait for it to finish", 409)


def edit_item(session, paypal, store, spec, version, item_id, changes, resolve=()):
    # changes: any of name, description, unit_price, category, stock, published.
    # resolve: flagged fields the merchant looked at and confirmed.
    # Everything is checked before anything is written, so a refused edit changes nothing
    require_editable(store)
    item = spec.find_item(item_id)
    if item is None:
        raise ReviewError("This store has no item " + str(item_id), 404)
    for field in resolve:
        if field not in FLAG_FIELDS:
            raise ReviewError(str(field) + " is not a field that can be flagged", 422)

    rows = ensure_reviews(session, store, spec)
    row = rows[item_id]
    runs = store_runs(session, store.id)
    history = spec_history(session, store.id)
    currency = spec.merchant.currency

    # 1. validate
    updates = {}
    if "name" in changes:
        name = str(changes["name"] or "").strip()
        if not name:
            raise ReviewError("An item needs a name", 422)
        if name != item.name:
            updates["name"] = name
    if "description" in changes:
        description = str(changes["description"] or "").strip()
        if description != item.description:
            updates["description"] = description
    if "unit_price" in changes:
        price = clean_price(changes["unit_price"])
        if price != item.unit_price:
            updates["unit_price"] = price

    if "category" in changes and changes["category"] is not None \
            and changes["category"] not in CATEGORIES:
        raise ReviewError(str(changes["category"]) + " is not one of the categories", 422)
    if "stock" in changes and changes["stock"] is not None:
        stock = changes["stock"]
        if isinstance(stock, bool) or not isinstance(stock, int) or stock < 0 or stock > MAX_STOCK:
            raise ReviewError("Stock has to be a whole number from 0 to " + str(MAX_STOCK), 422)

    edited = item
    if updates:
        data = item.model_dump()
        data.update(updates)
        try:
            edited = parse_item(data)
        except SpecError as error:
            raise ReviewError(str(error), 422) from error

    # 2. a new name or price has to hold up at PayPal before it is saved
    new_run = None
    if edited.available and ("name" in updates or "unit_price" in updates):
        ok, reason, order_id, _repairable = paypal_check(
            edited, currency, paypal, "edit-" + str(store.id) + "-" + item.id
        )
        if not ok:
            raise ReviewError("PayPal didn't accept the change: " + str(reason), 502)
        backed = page_backed_price(history, runs, item.id)
        on_page = backed == edited.unit_price
        note = None
        if not on_page:
            note = "Price set by the merchant"
            if backed is not None:
                note += ", the page check last passed at " + show_money(backed, currency)
        attempt = max((run.attempt for run in runs if run.item_id == item.id), default=0)
        new_run = VerificationRun(
            store_id=store.id, item_id=item.id, attempt=attempt, spec_version=version + 1,
            page_check_ok=on_page, paypal_check_ok=True, paypal_order_id=order_id, ok=True,
            reason=note,
        )

    # 3. write
    if updates:
        items = [edited if entry.id == item.id else entry for entry in spec.items]
        try:
            new_spec = parse_spec(spec.model_copy(update={"items": items}).model_dump())
        except SpecError as error:
            raise ReviewError(str(error), 422) from error
        parts = []
        for field in ("name", "unit_price", "description"):
            if field in updates:
                label = "price" if field == "unit_price" else field
                parts.append(label + ' "' + getattr(item, field) + '" to "' + updates[field] + '"')
        session.add(StoreSpecRow(
            store_id=store.id, version=version + 1, spec_json=spec_to_json(new_spec),
            note=("Merchant edit of " + item.name + ": " + ", ".join(parts))[:1000],
        ))
        if new_run is not None:
            session.add(new_run)
        spec = new_spec

    if "category" in changes:
        row.category = changes["category"]
    if "stock" in changes:
        row.stock = changes["stock"]

    resolved = resolved_map(row)
    for field in ("name", "unit_price"):
        if field not in updates:
            continue
        before = resolved.get(field)
        if before is None:
            # correcting a field settles it. remember what the agent had
            resolved[field] = {"by": "edit", "was": getattr(item, field)}
        elif before.get("by") == "edit" and before.get("was") == updates[field]:
            # the agent's value is back (an undo), so the doubt about it is back too
            del resolved[field]
    for field in resolve:
        resolved[field] = {"by": "confirm"}
    row.resolved_fields = json.dumps(resolved, sort_keys=True)
    session.flush()

    # publishing is decided on the state after the edit
    runs_after = runs + ([new_run] if new_run is not None else [])
    flags = compute_flags(spec, spec_history(session, store.id), runs_after).get(item.id, {})
    run = latest_runs(runs_after).get(item.id)
    blocked = blocked_reason(edited, run, flags, row)
    if changes.get("published") is True:
        if blocked:
            session.rollback()
            raise ReviewError(blocked + ", so it can't go live yet", 409)
        row.published = True
    elif changes.get("published") is False:
        row.published = False
    elif blocked and row.published:
        # an undo brought a flag back, so it has to be looked at again before it sells
        row.published = False

    # an edit can rescue a store where nothing had verified
    if new_run is not None and store.status == models.FAILED:
        store.status = models.LIVE
        store.error = None
    session.commit()
    return spec


def set_published(session, store, spec, item_ids, published):
    # all or nothing: one blocked item and none of them change
    require_editable(store)
    rows = ensure_reviews(session, store, spec)
    runs = store_runs(session, store.id)
    flags = compute_flags(spec, spec_history(session, store.id), runs)
    latest = latest_runs(runs)

    blocked = []
    for item_id in item_ids:
        item = spec.find_item(item_id)
        if item is None:
            raise ReviewError("This store has no item " + str(item_id), 404)
        if published:
            reason = blocked_reason(item, latest.get(item_id), flags.get(item_id, {}),
                                    rows[item_id])
            if reason:
                blocked.append({"item_id": item_id, "reason": reason})
    if blocked:
        count = len(blocked)
        raise ReviewError(
            str(count) + (" item" if count == 1 else " items") + " can't be published: "
            + "; ".join(entry["reason"] for entry in blocked),
            409, {"blocked": blocked},
        )
    for item_id in item_ids:
        rows[item_id].published = published
    session.commit()


def reorder(session, store, spec, item_ids):
    require_editable(store)
    rows = ensure_reviews(session, store, spec)
    if sorted(item_ids) != sorted(item.id for item in spec.items):
        raise ReviewError("The new order has to list every item of the store exactly once", 422)
    for position, item_id in enumerate(item_ids):
        rows[item_id].position = position
    session.commit()


def set_label(session, store, field, label):
    if field not in COLUMNS:
        raise ReviewError(str(field) + " is not a catalog column", 404)
    label = " ".join(str(label or "").split())
    if len(label) > MAX_LABEL_LENGTH:
        raise ReviewError(
            "A column name can be " + str(MAX_LABEL_LENGTH) + " characters at most", 422
        )
    session.execute(
        delete(ColumnLabel).where(ColumnLabel.store_id == store.id, ColumnLabel.field == field)
    )
    # blank, or the default again, means "not renamed"
    if label and label != COLUMNS[field][0]:
        session.add(ColumnLabel(store_id=store.id, field=field, label=label))
    session.commit()


def take_stock(session, store_id, item_id, quantity):
    # after a captured order. stock that isn't tracked stays untracked
    row = session.execute(
        select(ItemReview).where(ItemReview.store_id == store_id, ItemReview.item_id == item_id)
    ).scalars().first()
    if row is not None and row.stock is not None:
        row.stock = max(0, row.stock - quantity)
        session.commit()
