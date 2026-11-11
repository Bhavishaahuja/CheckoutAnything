# What the API routes and the shopping agent both need: reading stores, specs and catalogs,
# and buying. One place, so the agent's tools and the HTTP endpoints can't drift apart.

import json

from sqlalchemy import delete, select

from backend.app import models, review
from backend.app.models import ColumnLabel, ItemReview, Order, Store, StoreSpecRow, VerificationRun
from backend.app.orders import (
    OrderError,
    order_to_dict,
    place_order,
    place_order_through_check,
    price_order,
    refresh_check_orders,
)
from backend.app.spec import parse_spec, spec_to_json


def get_store(session, store_id):
    return session.get(Store, store_id)


def latest_spec_row(session, store_id):
    query = (
        select(StoreSpecRow)
        .where(StoreSpecRow.store_id == store_id)
        .order_by(StoreSpecRow.version.desc())
        .limit(1)
    )
    return session.execute(query).scalars().first()


def latest_spec(session, store_id):
    # (spec, version) or (None, 0)
    row = latest_spec_row(session, store_id)
    if row is None:
        return None, 0
    return parse_spec(json.loads(row.spec_json)), row.version


def save_spec(session, store_id, spec, note):
    row = latest_spec_row(session, store_id)
    version = 1 if row is None else row.version + 1
    session.add(StoreSpecRow(
        store_id=store_id, version=version, spec_json=spec_to_json(spec), note=note
    ))
    session.commit()
    return version


def runs_for_store(session, store_id):
    query = (
        select(VerificationRun)
        .where(VerificationRun.store_id == store_id)
        .order_by(VerificationRun.id)
    )
    return list(session.execute(query).scalars())


def latest_run_per_item(session, store_id):
    # item id -> its most recent verification run
    latest = {}
    for run in runs_for_store(session, store_id):
        latest[run.item_id] = run
    return latest


def verified_item_ids(session, store_id):
    verified = set()
    for item_id, run in latest_run_per_item(session, store_id).items():
        if run.ok:
            verified.add(item_id)
    return verified


def run_to_dict(run):
    return {
        "item_id": run.item_id,
        "attempt": run.attempt,
        "spec_version": run.spec_version,
        "page_check_ok": run.page_check_ok,
        "paypal_check_ok": run.paypal_check_ok,
        "paypal_order_id": run.paypal_order_id,
        "ok": run.ok,
        "reason": run.reason,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def store_to_dict(session, store):
    spec, _version = latest_spec(session, store.id)
    # live: verified and published, so an agent can actually buy it. the same rule as get_catalog
    counts = {"verified": 0, "failed": 0, "unavailable": 0, "live": 0}
    if spec is not None:
        latest = latest_run_per_item(session, store.id)
        reviews = review.ensure_reviews(session, store, spec)
        for item in spec.items:
            if not item.available:
                counts["unavailable"] += 1
            elif item.id in latest and latest[item.id].ok:
                counts["verified"] += 1
                row = reviews.get(item.id)
                if row is not None and row.published:
                    counts["live"] += 1
            elif item.id in latest:
                counts["failed"] += 1
    return {
        "id": store.id,
        "source_url": store.source_url,
        "merchant_name": store.merchant_name,
        "status": store.status,
        "mode": store.mode,
        "error": store.error,
        "counts": counts,
        "created_at": store.created_at.isoformat() if store.created_at else None,
    }


def list_stores(session, live_only=False):
    query = select(Store).order_by(Store.id)
    stores = []
    for store in session.execute(query).scalars():
        if live_only and store.status != models.LIVE:
            continue
        stores.append(store_to_dict(session, store))
    return stores


def get_catalog(session, store):
    # verified and published items only, in the merchant's order. this is what an agent is
    # allowed to buy
    spec, version = latest_spec(session, store.id)
    if spec is None:
        return None
    verified = verified_item_ids(session, store.id)
    reviews = review.ensure_reviews(session, store, spec)
    items = []
    for item in spec.items:
        row = reviews.get(item.id)
        if item.available and item.id in verified and row is not None and row.published:
            items.append((row.position, {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "category": row.category,
                "unit_price": item.unit_price,
                # None when the merchant doesn't track stock
                "stock": row.stock,
                "variants": [variant.model_dump() for variant in item.variants],
                "add_ons": [add_on.model_dump() for add_on in item.add_ons],
            }))
    items.sort(key=lambda entry: entry[0])
    items = [entry for _position, entry in items]
    labels = review.labels_for(session, store.id)
    return {
        "store_id": store.id,
        "merchant": spec.merchant.model_dump(),
        "source_url": store.source_url,
        "spec_version": version,
        "shipping": spec.shipping.model_dump(),
        # what the merchant calls each field, renamed columns included
        "field_labels": {
            field: labels[field]
            for field in ("name", "category", "description", "unit_price", "stock")
        },
        "items": items,
    }


def buy(session, paypal, vault_id, store_id, item_id, variant_id=None, add_on_ids=None,
        quantity=1, created_by="manual", check=None, mandate_for=None):
    # prices from the verified spec and pays. raises OrderError when it can't even be tried.
    # with check (a CheckClient) and mandate_for, the priced order goes to Check instead of
    # being paid here. mandate_for(store) returns the mandate id, and is only called once the
    # order has been priced, so a request that can't be bought never makes a mandate
    store = get_store(session, store_id)
    if store is None:
        raise OrderError("There is no store " + str(store_id), 404)
    if store.status != models.LIVE:
        raise OrderError(
            (store.merchant_name or "This store") + " isn't live, nothing can be bought", 409
        )
    spec, _version = latest_spec(session, store.id)
    if spec is None:
        raise OrderError("This store has no spec yet", 409)

    quote = price_order(
        spec, verified_item_ids(session, store.id), item_id, variant_id, add_on_ids, quantity
    )
    # the merchant's side: the item has to be published, and in stock when stock is tracked
    row = review.ensure_reviews(session, store, spec).get(item_id)
    if row is None or not row.published:
        raise OrderError(
            quote.line_name + " isn't live on PayPal yet, the merchant hasn't published it", 409
        )
    if row.stock is not None and quote.quantity > row.stock:
        if row.stock == 0:
            raise OrderError(quote.line_name + " is out of stock", 409)
        raise OrderError("Only " + str(row.stock) + " of " + quote.line_name + " left", 409)

    if check is not None and mandate_for is not None:
        order = place_order_through_check(
            session, check, mandate_for, vault_id, store, quote, created_by
        )
    else:
        order = place_order(session, paypal, vault_id, store, quote, created_by)
    if order.status == "captured":
        review.take_stock(session, store.id, item_id, quote.quantity)
    return order_to_dict(order, store.merchant_name), quote


def list_orders(session, check=None):
    names = {}
    for store in session.execute(select(Store)).scalars():
        names[store.id] = store.merchant_name
    rows = list(session.execute(select(Order).order_by(Order.id.desc())).scalars())
    # orders held at Check get their newest state first. a no-op without Check
    refresh_check_orders(session, check, rows)
    # newest first, including a fix's replacement order that the refresh just made a row for
    rows.sort(key=lambda order: -order.id)
    # Check's order id to ours, to link a fixed order and its replacement by the ids the grid has
    ours = {}
    for order in rows:
        if order.check_order_id is not None:
            ours[order.check_order_id] = order.id
    orders = []
    for order in rows:
        listed = order_to_dict(order, names.get(order.store_id))
        listed["replaced_by_order_id"] = ours.get(order.check_replaced_by_id)
        listed["replaces_order_id"] = ours.get(order.check_replaces_id)
        orders.append(listed)
    return orders


def get_order(session, order_id):
    return session.get(Order, order_id)


def wipe_everything(session, keep_check_order_ids=None):
    # /demo/reset. only forgets things here, orders and captures stay at PayPal.
    # keep_check_order_ids are the orders Check's own reset keeps (its PROTECTED_ORDER_IDS, the
    # order the sandbox dispute is on). our row for one stays too, so the Orders tab still shows
    # it, and so does its store row until relink_kept_orders moves it to the reconnected store.
    # returns {our order id: the old store's URL} for the kept ones
    keep_check_order_ids = set(keep_check_order_ids or [])
    kept = {}
    kept_store_ids = set()
    if keep_check_order_ids:
        query = select(Order).where(Order.check_order_id.in_(keep_check_order_ids))
        for order in session.execute(query).scalars():
            store = session.get(Store, order.store_id)
            kept[order.id] = store.source_url if store is not None else None
            kept_store_ids.add(order.store_id)

    session.execute(delete(Order).where(Order.id.not_in(list(kept))))
    session.execute(delete(ItemReview))
    session.execute(delete(ColumnLabel))
    session.execute(delete(VerificationRun))
    session.execute(delete(StoreSpecRow))
    session.execute(delete(Store).where(Store.id.not_in(list(kept_store_ids))))
    session.commit()
    return kept


def relink_kept_orders(session, kept, new_store_for_url, new_store_ids):
    # after the reset has started connecting the demo stores again: each kept order moves to the
    # new store for its old store's page, then the old store rows go. new_store_for_url(url) is
    # the new store's id, or None when the reset didn't reconnect that page. an order like that
    # can't show without a store, so our row goes (Check still has the order)
    if not kept:
        return
    for order_id, old_url in kept.items():
        order = session.get(Order, order_id)
        new_store_id = new_store_for_url(old_url) if old_url else None
        if new_store_id is None:
            session.delete(order)
        else:
            order.store_id = new_store_id
    session.flush()
    in_use = set(session.execute(select(Order.store_id)).scalars())
    for store_id in set(session.execute(select(Store.id)).scalars()):
        # only the old stores the kept orders were holding on to. the new ones are connecting
        if store_id not in in_use and store_id not in new_store_ids:
            session.delete(session.get(Store, store_id))
    session.commit()
