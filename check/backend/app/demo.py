# Demo support. Two separate things live here:
#   POST /demo/orders builds an order from a mandate's rules, right or wrong on purpose, and sends
#   it down the same path as an agent's order. It's what the /place-order page calls.
#   POST /demo/reset puts the demo back to the same starting point every time, in the background:
#     1. voids every open hold at PayPal (refused up front if a human opened one in the last 10
#        minutes, or has a payment going through)
#     2. deletes every order and mandate that isn't protected, with their check results,
#        decisions and disputes: the last seed, old test runs, manual testing, /place-order
#        orders. protected means PROTECTED_ORDER_IDS names its Check order id. that's how the
#        order the sandbox dispute is on stays, with its dispute row, so the Disputes tab has it
#     3. places the seed again through the real agent path, see demo_seed.py. a seed order for
#        the same item at the same store as a kept order is skipped, so the grid doesn't show
#        two blanket orders telling the same story
#   GET /demo/reset says how far it got. backend/scripts/seed_demo.py --reset calls both.

import enum
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from backend.app import catalog, demo_seed
from backend.app.auth import require_merchant
from backend.app.config import STORE_NAME, get_settings
from backend.app.config import protected_order_ids as protected_order_ids_setting
from backend.app.demo_seed import SEED_LABEL_PREFIX  # noqa: F401 (seed_demo.py reads it here)
from backend.app.intent.rules import as_utc, normalize_merchant
from backend.app.models import (
    Approval,
    Decision,
    Dispute,
    Mandate,
    Order,
    OrderStatus,
    ReviewState,
)
from backend.app.orders import (
    CENT,
    CLAIM_EXPIRES_AFTER,
    PAYPAL_FAILURES,
    VOID,
    Claude,
    DbSession,
    OrderDetail,
    OrderItemIn,
    PayPal,
    claim_order,
    load_order,
    payment_request_id,
    place_order,
    release_claim,
    utc_now,
)
from backend.app.review import hold_has_expired
from backend.app.session import RateLimiter, client_address

logger = logging.getLogger(__name__)

CLEAN_SHARE_OF_CAP = Decimal("0.80")
OVER_CAP_SHARE_OF_CAP = Decimal("1.15")
# a mandate with no cap gets the item's real catalog price. this is only for an item we don't
# have a price for: the shopper set no limit, so any price passes the rule and this number
# doesn't affect the verdict
PRICE_WITHOUT_CAP = Decimal("50.00")
# shipping stays out of it, so the percentages above are exactly what the price rule compares
DEMO_SHIPPING = Decimal("0.00")

# the other store from the seed data, for the wrong_store scenario
OTHER_STORE_NAME = "Ridgeline Outdoors"
# first one that doesn't appear in the mandate's color wins
WRONG_COLORS = ["red", "green", "orange"]

# POST /demo/reset per address. enough to reset, look, and reset again, not enough to hammer
# PayPal with voids. per process and in memory, like the login limit
RESET_MAX_TRIES = 3
RESET_WINDOW_SECONDS = 60
reset_limiter = RateLimiter(RESET_MAX_TRIES, RESET_WINDOW_SECONDS)

# a review page opened this recently counts as a human still deciding, and the reset waits for them.
# one opened longer ago than this was walked away from, and the reset clears it
MID_DECISION_WINDOW = timedelta(minutes=10)

# who a /place-order order is credited to. the merchant placed it, standing in for an agent, so it
# gets its own name instead of borrowing a real agent's
DEMO_AGENT_NAME = "Demo page"

router = APIRouter(prefix="/demo", tags=["demo"])


class DemoScenario(str, enum.Enum):
    clean = "clean"
    wrong_color = "wrong_color"
    over_cap = "over_cap"
    wrong_store = "wrong_store"
    # these five pick their wrong variant from the catalog, see catalog.py
    wrong_size = "wrong_size"
    substitution = "substitution"
    wrong_model = "wrong_model"
    wrong_date = "wrong_date"
    # one more unit, at the real unit price when the catalog has one
    wrong_quantity = "wrong_quantity"


# the ones the catalog decides. GET /mandates says which of these each mandate can run, so the
# page's buttons can't disagree with build_demo_order
CATALOG_SCENARIOS = [
    DemoScenario.wrong_size,
    DemoScenario.substitution,
    DemoScenario.wrong_model,
    DemoScenario.wrong_date,
]


class DemoOrderCreate(BaseModel):
    mandate_id: int
    scenario: DemoScenario


@dataclass(frozen=True)
class DemoOrder:
    items: list[OrderItemIn]
    shipping: Decimal
    merchant: str | None


class ScenarioNotPossible(Exception):
    # this mandate has nothing for the scenario to break. a "wrong color" on a mandate that names
    # no color is a perfectly fine order, and it would auto-capture while pretending to be a test
    pass


def build_demo_order(mandate, scenario, catalog_rows=None):
    # no database and no PayPal in here, just the mandate's rules turned into an order. each
    # scenario starts from the same matching order and breaks exactly one thing.
    # catalog_rows is the catalog for the mandate's category (catalog.load_category), the
    # scenarios that need a real sibling variant pick it from there. a mandate at one of the
    # Connect stores gets its sizes and prices from store_catalogs.py instead
    if catalog_rows is None:
        catalog_rows = []
    rules = mandate.rules
    # checked first, every scenario needs it. a placeholder name can't be checked against anything,
    # so Claude says unsure and even a clean order can never auto-capture
    item_name = product_name(rules.get("item"))
    if item_name is None:
        raise ScenarioNotPossible("This mandate doesn't name an item to order")

    color = rules.get("color")
    size = rules.get("size")
    model = rules.get("model")
    event_date = catalog.parse_event_date(rules.get("event_date"))
    # same fallback as the parser: a shopper who didn't say how many wants one
    quantity = rules.get("quantity") or 1
    merchant = mandate.merchant
    # the sizes the item really comes in and the real price of the one asked for. empty and None
    # when we don't know the item
    sizes = catalog.item_sizes(merchant, item_name, rules, catalog_rows)
    catalog_unit_price = catalog.price_of_size(sizes, size)
    target_total = clean_total(mandate, catalog_unit_price, quantity)
    rounding = ROUND_DOWN

    if scenario == DemoScenario.wrong_color:
        if not color:
            raise ScenarioNotPossible("This mandate doesn't name a color to get wrong")
        color = different_color(color)
    elif scenario == DemoScenario.over_cap:
        if mandate.max_price is None:
            raise ScenarioNotPossible("This mandate has no price cap to go over")
        target_total = Decimal(str(mandate.max_price)) * OVER_CAP_SHARE_OF_CAP
        # up, so a small cap split across several units still lands over it
        rounding = ROUND_UP
    elif scenario == DemoScenario.wrong_store:
        if not merchant:
            raise ScenarioNotPossible("This mandate doesn't name a store, so any store is fine")
        merchant = different_store(merchant)
    elif scenario == DemoScenario.wrong_size:
        if not size:
            raise ScenarioNotPossible("This mandate doesn't name a size to get wrong")
        if catalog.word_size_rank(size) is not None:
            # Small, Medium, Large: the next size over that the store really has, at its own
            # price. a Medium blanket costs more than a Small one, and the order should say so
            if not sizes:
                raise ScenarioNotPossible("This mandate isn't for anything in the store's catalog")
            next_size = catalog.next_word_size(sizes, size)
            if next_size is None:
                raise ScenarioNotPossible("The catalog has no other size of this")
            size = next_size["label"]
            target_total = next_size["unit_price"] * quantity
        else:
            # number sizes (sneakers) work the way they always have: nearest size, same total
            require_catalog(catalog_rows)
            size = catalog.other_size(catalog_rows, size)
            if size is None:
                raise ScenarioNotPossible("The catalog has no other size of this")
    elif scenario == DemoScenario.substitution:
        require_catalog(catalog_rows)
        substitute = catalog.substitute_for(catalog_rows, item_name)
        if substitute is None:
            raise ScenarioNotPossible("The catalog has nothing else in this category to swap in")
        item_name = substitute.name
    elif scenario == DemoScenario.wrong_model:
        if not model:
            raise ScenarioNotPossible("This mandate doesn't name a model to get wrong")
        require_catalog(catalog_rows)
        model = catalog.other_model(catalog_rows, model)
        if model is None:
            raise ScenarioNotPossible("The catalog has no other model of this")
    elif scenario == DemoScenario.wrong_date:
        if event_date is None:
            raise ScenarioNotPossible("This mandate doesn't name an event date to get wrong")
        require_catalog(catalog_rows)
        event_date = catalog.other_event_date(catalog_rows, event_date)
        if event_date is None:
            raise ScenarioNotPossible("The catalog has no other date for this event")
    elif scenario == DemoScenario.wrong_quantity:
        if catalog_unit_price is not None:
            # one more at the price the store really charges. if that goes over the cap, the
            # price rule holds it before Claude does, and that's fine: it's still held
            target_total = catalog_unit_price * (quantity + 1)
        else:
            # no real price to keep to, so the same money as the clean order spread over one more
            # unit. then the total can't trip the cap and the test is about Claude.
            # one more and not a dozen, so the unit price still looks like a real price on camera
            clean_unit_price = (target_total / quantity).quantize(CENT, rounding=ROUND_DOWN)
            target_total = clean_unit_price * quantity
        quantity += 1

    unit_price = (target_total / quantity).quantize(CENT, rounding=rounding)
    try:
        # name, color and size stay separate fields, like an agent's order. item_display_name in
        # orders.py and describeItem in the frontend join them into "Trail runners, blue, size 8",
        # so putting the color in the name as well would print it twice
        item = OrderItemIn(
            name=item_name,
            color=color,
            size=size,
            model=model,
            event_date=event_date,
            quantity=quantity,
            unit_price=unit_price,
        )
    except ValidationError as error:
        # a cap of one cent, or a quantity or price past what POST /orders accepts
        raise ScenarioNotPossible("This mandate's values can't make a valid order") from error

    return DemoOrder(items=[item], shipping=DEMO_SHIPPING, merchant=merchant)


def require_catalog(catalog_rows):
    # the mandate's category isn't one the store sells (or the parser didn't give one), so there's
    # no real sibling variant to pick
    if not catalog_rows:
        raise ScenarioNotPossible("This mandate isn't for anything in the store's catalog")


def product_name(item):
    # "trail runners" from the parser reads as "Trail runners" on a product line. None if blank
    if not item or not item.strip():
        return None
    name = item.strip()
    return name[0].upper() + name[1:]


def clean_total(mandate, catalog_unit_price=None, quantity=1):
    if mandate.max_price is not None:
        return Decimal(str(mandate.max_price)) * CLEAN_SHARE_OF_CAP
    # no cap: what the store really charges, when we know it
    if catalog_unit_price is not None:
        return catalog_unit_price * quantity
    return PRICE_WITHOUT_CAP


def possible_catalog_scenarios(mandate, catalog_rows):
    # the catalog scenarios build_demo_order would really build for this mandate. it's asked, not
    # worked out a second time, so the page's buttons can't drift from it
    possible = []
    for scenario in CATALOG_SCENARIOS:
        try:
            build_demo_order(mandate, scenario, catalog_rows)
        except ScenarioNotPossible:
            continue
        possible.append(scenario.value)
    return possible


def different_color(color):
    wanted = color.casefold()
    for candidate in WRONG_COLORS:
        if candidate not in wanted:
            return candidate
    # a mandate would have to name all of them for this to run
    return "purple"


def different_store(merchant):
    if normalize_merchant(merchant) == normalize_merchant(OTHER_STORE_NAME):
        return STORE_NAME
    return OTHER_STORE_NAME


@router.post(
    "/orders",
    response_model=OrderDetail,
    status_code=201,
    dependencies=[Depends(require_merchant)],
)
def create_demo_order(body: DemoOrderCreate, session: DbSession, paypal: PayPal, claude: Claude):
    # checked first so a missing setting can't leave half an order behind
    vault_id = get_settings().demo_vault_id
    if not vault_id:
        raise HTTPException(status_code=503, detail="DEMO_VAULT_ID isn't set on the API")

    mandate = session.get(Mandate, body.mandate_id)
    if mandate is None:
        raise HTTPException(
            status_code=404, detail="Mandate " + str(body.mandate_id) + " not found"
        )

    catalog_rows = catalog.load_category(session, mandate.rules.get("category"))
    try:
        demo_order = build_demo_order(mandate, body.scenario, catalog_rows)
    except ScenarioNotPossible as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    order, _ = place_order(
        session,
        mandate,
        demo_order.items,
        demo_order.shipping,
        vault_id,
        paypal,
        claude,
        merchant=demo_order.merchant,
        agent_name=DEMO_AGENT_NAME,
    )

    # read it back, so this shows what got saved and not what the session remembers
    order_id = order.id
    session.expire_all()
    return load_order(session, order_id)




# ---- Reset demo: wipe, then seed ----


class SeedOrderOut(BaseModel):
    # one seed order and where it landed. problem is null when it landed where it should
    name: str
    agent_name: str
    store: str
    expected: str
    order_id: int | None
    status: str | None
    review_state: str | None
    problem: str | None


class ResetStatus(BaseModel):
    # what POST /demo/reset is doing, or did last. GET /demo/reset reads it while it runs
    #   idle      nothing since the API started
    #   running   step says which part it's on
    #   done      wiped and reseeded. orders lists every seed order
    #   failed    error says why. if it failed before the wipe, nothing was deleted
    state: str
    step: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # kept: the orders PROTECTED_ORDER_IDS names that are really there, the dispute's order
    protected_order_ids: list[int] = []
    voided_holds: int = 0
    # so the merchant can match them up with PayPal's records
    voided_order_ids: list[int] = []
    deleted_orders: int = 0
    deleted_disputes: int = 0
    # seed orders left out because a kept order already tells that story, by name
    skipped_seed_orders: list[str] = []
    deleted_mandates: int = 0
    # "Opened, deciding" left behind on a kept order, with nobody deciding any more
    cleared_reviews: int = 0
    orders_total: int = 0
    orders_placed: int = 0
    orders: list[SeedOrderOut] = []


class ResetBlocked(Exception):
    # the reset stopped partway, or never started. nothing still on hold at PayPal was deleted
    def __init__(self, status_code, detail):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


class ResetJob:
    # the one reset this API process runs at a time. in memory, like the rate limit: Render runs
    # one instance, and a restart mid-reset just leaves it to be pressed again
    def __init__(self):
        self.lock = threading.Lock()
        self.status = ResetStatus(state="idle")
        self.thread = None

    def snapshot(self):
        with self.lock:
            return self.status.model_copy(deep=True)

    def update(self, **changes):
        with self.lock:
            for field, value in changes.items():
                setattr(self.status, field, value)

    def add_order(self, result):
        with self.lock:
            self.status.orders.append(SeedOrderOut(**result))
            self.status.orders_placed = len(self.status.orders)
            self.status.step = (
                "Placing seed orders through Check, " + str(self.status.orders_placed)
                + " of " + str(self.status.orders_total) + " done"
            )

    def try_start(self):
        # True if this caller gets to run the reset. one at a time
        with self.lock:
            if self.status.state == "running":
                return False
            self.status = ResetStatus(
                state="running", step="Starting", started_at=utc_now(),
                orders_total=len(demo_seed.SEED_ORDERS),
            )
            return True


reset_job = ResetJob()


def protected_order_ids(session):
    # orders a reset keeps, whatever else it deletes: the ones PROTECTED_ORDER_IDS names that are
    # really in the database. nothing else is kept, not even an order with a dispute on it: an old
    # test order's dispute goes with the order, so it stops turning up in the grid
    wanted = protected_order_ids_setting(get_settings())
    kept = set()
    if wanted:
        query = select(Order.id).where(Order.id.in_(wanted))
        kept.update(session.scalars(query).all())
    return kept


def item_key(store, item_name):
    # "Wool Camp Blanket" at "Fernwood & Thistle Goods", whatever the case or the add-ons.
    # "Sourdough Loaf + Sliced" is the same loaf as "Sourdough Loaf"
    name = (item_name or "").split("+")[0]
    return (normalize_merchant(store or ""), " ".join(name.casefold().split()))


def seed_scenarios_without_duplicates(session, kept_ids):
    # returns (scenarios to place, names of the ones skipped). a kept order is the real version
    # of a seed story (the protected dispute order is a held blanket the human approved), so the
    # seed order for the same item at the same store would just be a confusing second copy
    kept_items = set()
    if kept_ids:
        for order in session.scalars(select(Order).where(Order.id.in_(kept_ids))).all():
            store = order.merchant or order.mandate.merchant
            for item in order.items or []:
                kept_items.add(item_key(store, item.get("name")))

    placing = []
    skipped = []
    for scenario in demo_seed.SEED_ORDERS:
        store = scenario.get("order_at", scenario["store"])
        duplicate = False
        for item in scenario["items"]:
            if item_key(store, item["name"]) in kept_items:
                duplicate = True
        if duplicate:
            skipped.append(scenario["name"])
        else:
            placing.append(scenario)
    return placing, skipped


def wipe_order_ids(session):
    # every order a reset deletes: everything that isn't protected. old test runs, the last seed,
    # orders from manual testing and from /place-order all go, so every reset ends the same
    kept = protected_order_ids(session)
    wiped = []
    for order_id in session.scalars(select(Order.id).order_by(Order.id)).all():
        if order_id not in kept:
            wiped.append(order_id)
    return wiped


def has_open_hold(order):
    # money on hold at PayPal right now. an expired hold has nothing to void
    return order.status == OrderStatus.authorized and not hold_has_expired(order)


def deciding_now(session, order):
    # why a human is deciding this order right now, or None. a payment that's on its way to PayPal,
    # or a review page opened in the last MID_DECISION_WINDOW. an older opened page was left behind
    # and is fair game
    if order.payment_claimed_at is not None:
        if utc_now() - as_utc(order.payment_claimed_at) < CLAIM_EXPIRES_AFTER:
            return "Order " + str(order.id) + " has a payment going through right now"
    query = select(Approval).where(Approval.order_id == order.id, Approval.action.is_(None))
    for approval in session.scalars(query).all():
        if approval.opened_at is None:
            continue
        opened_for = utc_now() - as_utc(approval.opened_at)
        if opened_for < MID_DECISION_WINDOW:
            minutes = max(1, int(opened_for.total_seconds() // 60))
            return (
                "Someone opened the review for order " + str(order.id) + " " + str(minutes)
                + " min ago and may be deciding it. Try again once they're done, or after "
                + str(int(MID_DECISION_WINDOW.total_seconds() // 60)) + " minutes"
            )
    return None


def mid_decision_blockers(session):
    # every open hold a reset would void that a human is in the middle of. checked up front, so a
    # reset that would yank a hold from under someone's thumb never starts
    blockers = []
    wiped = wipe_order_ids(session)
    if wiped:
        for order in session.scalars(select(Order).where(Order.id.in_(wiped))).all():
            if not has_open_hold(order):
                continue
            reason = deciding_now(session, order)
            if reason is not None:
                blockers.append({"order_id": order.id, "message": reason})
    session.rollback()
    return blockers


def open_hold_ids(session):
    wiped = wipe_order_ids(session)
    open_ids = []
    if wiped:
        for order in session.scalars(select(Order).where(Order.id.in_(wiped))).all():
            if has_open_hold(order):
                open_ids.append(order.id)
    session.rollback()
    return open_ids


def void_hold(session, paypal, order_id):
    # the same steps as rejecting from a review link: claim it so a human tapping approve right
    # now can't capture it as well, void with the derived PayPal-Request-Id so a retry can't
    # double up, then save. no approval row, nobody actually reviewed it
    order, blocker = claim_order(session, order_id)
    if blocker is not None:
        session.rollback()
        raise ResetBlocked(409, {
            "message": "Order " + str(order_id) + " is being decided right now, try again",
            "order_id": order_id,
        })

    try:
        voided = paypal.void_authorization(
            order.authorization_id, request_id=payment_request_id(order, VOID)
        )
    except PAYPAL_FAILURES as error:
        release_claim(session, order_id)
        raise ResetBlocked(502, {
            "message": "PayPal couldn't void order " + str(order_id)
            + ". Nothing was deleted, try again",
            "order_id": order_id,
        }) from error

    try:
        order = load_order(session, order_id, lock=True)
        order.status = OrderStatus.voided
        order.review_state = ReviewState.rejected
        # a 204 with no body is also a documented success
        order.void_result = voided.get("status") if voided else "VOIDED"
        order.payment_claimed_at = None
        session.commit()
    except SQLAlchemyError as error:
        # voided at PayPal, not saved here. the claim expires and a retry gets PayPal's same
        # answer back for the same request id, so running the reset again sorts it out
        session.rollback()
        raise ResetBlocked(502, {
            "message": "Order " + str(order_id) + " was voided but saving that failed, try again",
            "order_id": order_id,
        }) from error


def delete_demo_rows(session):
    # deletes every order that isn't protected, with its check results and reviews, and every
    # mandate no kept order points at. refuses while any of those orders still has an open hold,
    # so deleting a row can't leave an authorization at PayPal that nothing knows about. captures
    # stay at PayPal, this only forgets them here.
    # returns (orders deleted, mandates deleted, disputes deleted, undecided reviews cleared on
    # kept orders)
    kept_ids = protected_order_ids(session)
    order_ids = wipe_order_ids(session)

    open_ids = []
    if order_ids:
        query = select(Order).where(Order.id.in_(order_ids)).with_for_update()
        for order in session.scalars(query).all():
            if has_open_hold(order):
                open_ids.append(order.id)
    if open_ids:
        session.rollback()
        raise ResetBlocked(409, {
            "message": "Void the open holds on these orders first",
            "open_order_ids": open_ids,
        })

    kept_mandate_ids = set()
    if kept_ids:
        query = select(Order.mandate_id).where(Order.id.in_(kept_ids))
        kept_mandate_ids.update(session.scalars(query).all())
    mandate_ids = []
    for mandate_id in session.scalars(select(Mandate.id).order_by(Mandate.id)).all():
        if mandate_id not in kept_mandate_ids:
            mandate_ids.append(mandate_id)

    # an accepted fix links two orders to each other. let go of every link first, so no database
    # has to work out which of a pair it's allowed to delete first
    session.execute(update(Order).values(replaced_by_order_id=None, replaces_order_id=None))
    # a dispute on a deleted order goes with it. the dispute stays at PayPal, it's just not ours
    # to show any more, and a later sync only looks at the orders that are left
    deleted_disputes = session.execute(
        delete(Dispute).where(Dispute.order_id.in_(order_ids))
    ).rowcount
    session.execute(delete(Approval).where(Approval.order_id.in_(order_ids)))
    session.execute(delete(Decision).where(Decision.order_id.in_(order_ids)))
    session.execute(delete(Order).where(Order.id.in_(order_ids)))
    session.execute(delete(Mandate).where(Mandate.id.in_(mandate_ids)))
    # a kept order can still show "Opened, deciding" from a page someone walked away from
    cleared = 0
    if kept_ids:
        cleared = session.execute(
            delete(Approval).where(Approval.order_id.in_(kept_ids), Approval.action.is_(None))
        ).rowcount
    session.commit()
    return len(order_ids), len(mandate_ids), deleted_disputes, cleared


def run_reset(session_factory, paypal, claude, job):
    # the whole reset, on its own thread: void, delete, seed. the first void that fails stops it
    # with the rows still there, so a hold is never forgotten while it still holds money. running
    # it again picks up where it stopped
    try:
        session = session_factory()
        try:
            kept_ids = protected_order_ids(session)
            job.update(protected_order_ids=sorted(kept_ids))
            scenarios, skipped = seed_scenarios_without_duplicates(session, kept_ids)
            job.update(skipped_seed_orders=skipped, orders_total=len(scenarios))
            session.rollback()

            voided_ids = []
            hold_ids = open_hold_ids(session)
            for order_id in hold_ids:
                job.update(step="Voiding open holds at PayPal, " + str(len(voided_ids))
                           + " of " + str(len(hold_ids)) + " done")
                void_hold(session, paypal, order_id)
                voided_ids.append(order_id)
                job.update(voided_holds=len(voided_ids), voided_order_ids=list(voided_ids))

            job.update(step="Clearing out the old demo orders")
            deleted_orders, deleted_mandates, deleted_disputes, cleared = delete_demo_rows(session)
            job.update(deleted_orders=deleted_orders, deleted_mandates=deleted_mandates,
                       deleted_disputes=deleted_disputes, cleared_reviews=cleared)
        finally:
            session.close()

        job.update(step="Placing seed orders through Check, 0 of "
                   + str(len(scenarios)) + " done")
        demo_seed.place_seed_orders(
            session_factory, paypal, claude, on_done=job.add_order, scenarios=scenarios
        )
        job.update(state="done", step=None, finished_at=utc_now())
    except ResetBlocked as error:
        message = error.detail.get("message") if isinstance(error.detail, dict) else error.detail
        job.update(state="failed", step=None, error=str(message), finished_at=utc_now())
    except Exception as error:  # noqa: BLE001
        # the thread has nobody to raise to. the log has it in full, the dashboard the short form
        logger.exception("Reset demo failed")
        job.update(state="failed", step=None, finished_at=utc_now(),
                   error="The reset stopped: " + type(error).__name__ + ": " + str(error)[:200])


@router.post(
    "/reset", response_model=ResetStatus, status_code=202,
    dependencies=[Depends(require_merchant)],
)
def reset_demo(request: Request, session: DbSession, paypal: PayPal, claude: Claude):
    # starts the reset and answers straight away. GET /demo/reset says how it's going
    if reset_job.snapshot().state == "running":
        raise HTTPException(status_code=409, detail="A reset is already running")

    # counted after the auth check, so only someone logged in can use up the allowance
    wait = reset_limiter.seconds_until_allowed(client_address(request))
    if wait > 0:
        raise HTTPException(
            status_code=429,
            detail="The demo was just reset, try again in a minute",
            headers={"Retry-After": str(int(wait) + 1)},
        )

    # both before anything is touched: a reset that can't seed would leave an empty demo, and one
    # that voids a hold someone is looking at pulls it out from under them
    problems = demo_seed.setup_problems(get_settings())
    if problems:
        raise HTTPException(status_code=503, detail={
            "message": "Can't seed the demo: " + problems[0], "problems": problems,
        })
    blockers = mid_decision_blockers(session)
    if blockers:
        order_ids = []
        for blocker in blockers:
            order_ids.append(blocker["order_id"])
        raise HTTPException(status_code=409, detail={
            "message": blockers[0]["message"], "order_ids": order_ids,
        })

    if not reset_job.try_start():
        raise HTTPException(status_code=409, detail="A reset is already running")
    # in the first answer, not just once the thread gets to it: Checkout Anything's own reset
    # reads it straight away to keep its row for the protected order
    reset_job.update(protected_order_ids=sorted(protected_order_ids(session)))
    session.rollback()

    # the thread gets its own sessions on the same database as this request
    session_factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    thread = threading.Thread(
        target=run_reset, args=(session_factory, paypal, claude, reset_job),
        name="reset-demo", daemon=True,
    )
    reset_job.thread = thread
    thread.start()
    return reset_job.snapshot()


@router.get("/reset", response_model=ResetStatus, dependencies=[Depends(require_merchant)])
def reset_status():
    return reset_job.snapshot()
