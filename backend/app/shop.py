# What the API routes and the shopping agent both need: reading stores, specs and catalogs,
# and buying. One place, so the agent's tools and the HTTP endpoints can't drift apart.

import json

from sqlalchemy import delete, select

from backend.app import models
from backend.app.models import Order, Store, StoreSpecRow, VerificationRun
from backend.app.orders import OrderError, order_to_dict, place_order, price_order
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
    counts = {"verified": 0, "failed": 0, "unavailable": 0}
    if spec is not None:
        latest = latest_run_per_item(session, store.id)
        for item in spec.items:
            if not item.available:
                counts["unavailable"] += 1
            elif item.id in latest and latest[item.id].ok:
                counts["verified"] += 1
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
    # verified items only. this is what an agent is allowed to buy
    spec, version = latest_spec(session, store.id)
    if spec is None:
        return None
    verified = verified_item_ids(session, store.id)
    items = []
    for item in spec.items:
        if item.available and item.id in verified:
            items.append({
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "unit_price": item.unit_price,
                "variants": [variant.model_dump() for variant in item.variants],
                "add_ons": [add_on.model_dump() for add_on in item.add_ons],
            })
    return {
        "store_id": store.id,
        "merchant": spec.merchant.model_dump(),
        "source_url": store.source_url,
        "spec_version": version,
        "shipping": spec.shipping.model_dump(),
        "items": items,
    }


def buy(session, paypal, vault_id, store_id, item_id, variant_id=None, add_on_ids=None,
        quantity=1, created_by="manual"):
    # prices from the verified spec and pays. raises OrderError when it can't even be tried
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
    order = place_order(session, paypal, vault_id, store, quote, created_by)
    return order_to_dict(order, store.merchant_name), quote


def list_orders(session):
    names = {}
    for store in session.execute(select(Store)).scalars():
        names[store.id] = store.merchant_name
    orders = []
    for order in session.execute(select(Order).order_by(Order.id.desc())).scalars():
        orders.append(order_to_dict(order, names.get(order.store_id)))
    return orders


def wipe_everything(session):
    # /demo/reset. only forgets things here, orders and captures stay at PayPal
    session.execute(delete(Order))
    session.execute(delete(VerificationRun))
    session.execute(delete(StoreSpecRow))
    session.execute(delete(Store))
    session.commit()
