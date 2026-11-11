# The API. Routes match section 7 of the build brief, plus /health and /config.
#
#   POST /stores/connect        start connecting a URL
#   GET  /stores/{id}/events    SSE stream of the connect run
#   GET  /stores                list stores + status
#   GET  /stores/{id}/catalog   verified items
#   GET  /stores/{id}/spec      full spec + extraction notes + version history + runs
#   GET  /stores/{id}/review    the merchant's review: flags, publish state, order, labels
#   PATCH /stores/{id}/items/{item_id}   edit, confirm or publish one item
#   POST /stores/{id}/publish   publish or unpublish several items
#   PUT  /stores/{id}/order     the order items appear in
#   PUT  /stores/{id}/columns/{field}    rename a catalog column
#   POST /stores/{id}/orders    buy (price computed server-side)
#   POST /agent/chat            demo shopping agent
#   GET  /orders                all orders
#   GET  /orders/agent-stats    per agent: orders through Check and how many it held
#   GET  /check/stats           Check's rubber-stamp watch and order count (merchant only)
#   POST /auth/session          the merchant's login, passed through to Check
#   POST /orders/{id}/review-link   link to the confirm page for an order on hold (Check).
#                                   needs the login
#   GET  /disputes, POST /disputes/sync, GET /disputes/{id}/evidence,
#   POST /disputes/{id}/redraft, POST /disputes/{id}/submit-evidence   (Defend)
#   POST /demo/reset            wipe demo data and reconnect the 3 demo stores

import json
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import check_client, connect, models, review, shop
from backend.app.agent import BUYER_LABEL, ShoppingAgent
from backend.app.check_client import CheckError
from backend.app.config import DEMO_STORE_SLUGS, allowed_fetch_hosts, cors_origins, get_settings
from backend.app.db import create_tables, get_session, new_session
from backend.app.demo import load_fixture
from backend.app.events import bus, sse_format
from backend.app.fetcher import FetchError, check_url, fetch_page
from backend.app.models import Order, Store, StoreSpecRow
from backend.app.orders import OrderError, held_rates
from backend.app.paypal_client import client_from_settings
from backend.app.verifier import describe_ai_error

logger = logging.getLogger(__name__)

DbSession = Annotated[Session, Depends(get_session)]

# what the strip above the orders grid calls each kind of order
AGENT_LABELS = {"agent": BUYER_LABEL, "manual": "Manual orders"}


# ---- request shapes ----


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)
    # left out, the API's DEMO_MODE decides
    mode: Literal["live", "replay"] | None = None


class OrderRequest(BaseModel):
    # no price field on purpose, and extra fields are rejected rather than ignored, so a
    # client that tries to send one finds out
    model_config = ConfigDict(extra="forbid")
    item_id: str = Field(min_length=1, max_length=60)
    variant_id: str | None = Field(default=None, max_length=60)
    add_on_ids: list[str] = Field(default_factory=list, max_length=20)
    quantity: int = Field(default=1, ge=1, le=100)


class ItemPatch(BaseModel):
    # only the fields that were sent are touched. unit_price is a string or number here, the
    # API cleans it up and refuses what isn't a price
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=400)
    unit_price: str | float | int | None = None
    category: str | None = Field(default=None, max_length=40)
    stock: int | None = None
    published: bool | None = None
    # flagged fields the merchant looked at and confirmed
    resolve: list[str] = Field(default_factory=list, max_length=10)


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_ids: list[str] = Field(min_length=1, max_length=60)
    published: bool = True


class OrderOfItems(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_ids: list[str] = Field(min_length=1, max_length=60)


class LabelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(max_length=200)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)
    # on an assistant message: the orders that turn placed, the ids /agent/chat sent back.
    # only ids, the agent reads the orders themselves from the database
    order_ids: list[int] = Field(default_factory=list, max_length=10)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    # demo only: the agent buys the next size over so Check has something to catch
    sloppy: bool = False


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=200)


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["live", "replay"] | None = None


def same_page_key(url):
    # two URLs for the same store page: the host's case and a trailing slash don't matter
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


# ---- app ----


def create_app(settings=None, paypal=None, ai_factory=None, fetch=None, agent_client=None,
               order_reader=None, check=None):
    # everything that reaches outside (PayPal, Claude, the page fetch, Check) can be swapped
    # in here, which is how the tests run without a network
    settings = settings or get_settings()
    paypal = paypal or client_from_settings(settings)
    # None unless CHECK_URL is set. every Check code path below starts from this
    check = check or check_client.client_from_settings(settings)
    ai_factory = ai_factory or connect.default_ai_factory
    fetch = fetch or fetch_page

    @asynccontextmanager
    async def lifespan(app):
        create_tables()
        # a run that was in flight when the API last stopped can never finish now
        session = new_session()
        try:
            stuck = session.execute(
                select(Store).where(Store.status == models.CONNECTING)
            ).scalars()
            for store in stuck:
                store.status = models.FAILED
                store.error = "The API restarted while this store was connecting"
            session.commit()
        finally:
            session.close()
        yield

    app = FastAPI(title="Checkout Anything", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(settings.frontend_origins),
        allow_methods=["GET", "POST", "PATCH", "PUT"],
        # Authorization carries the merchant's session to the review-link route
        allow_headers=["Content-Type", "Last-Event-ID", "Authorization"],
    )

    def begin_connect(session, url, mode):
        store = Store(source_url=url, status=models.CONNECTING, mode=mode)
        session.add(store)
        session.commit()
        if not connect.claim_run(store.id):
            store.status = models.FAILED
            store.error = "Too many stores are connecting right now"
            session.commit()
            raise HTTPException(
                status_code=429,
                detail="Too many stores are connecting right now, try again in a minute",
            )
        connect.start_connect(
            store.id, url, mode, settings, paypal, new_session, ai_factory, fetch
        )
        return store

    def find_connected_store(session, url):
        # a store for the same page that is connecting or connected. a failed one doesn't
        # count, connecting again is how you retry it
        wanted = same_page_key(url)
        stores = session.execute(select(Store).order_by(Store.id)).scalars()
        for store in stores:
            if store.status == models.FAILED:
                continue
            if same_page_key(store.source_url) == wanted:
                return store
        return None

    def demo_store_urls():
        base = settings.demo_stores_base_url.rstrip("/")
        return [base + "/" + slug + "/" for slug in DEMO_STORE_SLUGS]

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/config")
    def config():
        # what the frontend needs to draw itself. no secrets, only whether they are set
        fixtures = []
        for url in demo_store_urls():
            if load_fixture(url) is not None:
                fixtures.append(url)
        return {
            "default_mode": settings.demo_mode,
            "demo_store_urls": demo_store_urls(),
            "fixture_urls": fixtures,
            "paypal_configured": bool(settings.paypal_client_id and settings.paypal_client_secret),
            "claude_configured": bool(settings.anthropic_api_key),
            "vault_configured": bool(settings.buyer_vault_id),
            # agent orders go through Check
            "check_configured": check is not None,
            # the grid can show check results, review links and disputes
            "check_merchant_configured": check is not None and check.can_read,
            # orders on hold can be reviewed from the grid (after logging in)
            "check_review_links": check is not None and check.can_read
            and bool(settings.check_frontend_url),
        }

    # ---- connect ----

    @app.post("/stores/connect", status_code=202)
    def connect_store(body: ConnectRequest, session: DbSession):
        url = body.url.strip()
        mode = body.mode or settings.demo_mode
        # the same check the fetcher does, done here too so a bad URL is a 400 right away.
        # replay never fetches, but the URL still has to be a sane one
        try:
            check_url(url, allowed_fetch_hosts(settings.fetch_allow_hosts))
        except FetchError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        # the same page pasted twice is one store, not two the agent has to pick between
        existing = find_connected_store(session, url)
        if existing is not None:
            return {
                "store_id": existing.id,
                "mode": existing.mode,
                "events_url": "/stores/" + str(existing.id) + "/events",
                "already_connected": True,
                "message": "This store is already connected, showing it instead",
            }

        store = begin_connect(session, url, mode)
        return {"store_id": store.id, "mode": mode, "events_url": "/stores/" + str(store.id)
                + "/events", "already_connected": False, "message": None}

    @app.get("/stores/{store_id}/events")
    def store_events(store_id: int, session: DbSession,
                     last_event_id: Annotated[str | None, Header()] = None):
        store = shop.get_store(session, store_id)
        if store is None:
            raise HTTPException(status_code=404, detail="There is no store " + str(store_id))
        if store.status != models.CONNECTING and not bus.history(store_id):
            # the run finished before the API last restarted, the log is gone.
            # GET /stores/{id}/spec still has the result
            raise HTTPException(status_code=410, detail="This run's live log is gone")

        start = 0
        if last_event_id and last_event_id.isdigit():
            # a browser that reconnects says which event it saw last
            start = int(last_event_id) + 1

        def stream():
            for event in bus.stream(store_id, start):
                yield sse_format(event)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            # no caching, and tell proxies not to hold events back
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---- reading ----

    @app.get("/stores")
    def stores(session: DbSession):
        return {"stores": shop.list_stores(session)}

    @app.get("/stores/{store_id}/catalog")
    def catalog(store_id: int, session: DbSession):
        store = shop.get_store(session, store_id)
        if store is None:
            raise HTTPException(status_code=404, detail="There is no store " + str(store_id))
        found = shop.get_catalog(session, store)
        if found is None:
            raise HTTPException(status_code=409, detail="This store has no spec yet")
        found["status"] = store.status
        return found

    @app.get("/stores/{store_id}/spec")
    def spec(store_id: int, session: DbSession):
        store = shop.get_store(session, store_id)
        if store is None:
            raise HTTPException(status_code=404, detail="There is no store " + str(store_id))

        versions = []
        rows = session.execute(
            select(StoreSpecRow).where(StoreSpecRow.store_id == store_id)
            .order_by(StoreSpecRow.version)
        ).scalars()
        for row in rows:
            versions.append({
                "version": row.version,
                "note": row.note,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "spec": json.loads(row.spec_json),
            })

        latest = versions[-1]["spec"] if versions else None
        runs = [shop.run_to_dict(run) for run in shop.runs_for_store(session, store_id)]
        return {
            "store": shop.store_to_dict(session, store),
            "spec": latest,
            "extraction_notes": latest["extraction_notes"] if latest else [],
            "versions": versions,
            "runs": runs,
            "verified_item_ids": sorted(shop.verified_item_ids(session, store_id)),
        }

    # ---- the merchant's review ----

    def store_and_spec(session, store_id):
        store = shop.get_store(session, store_id)
        if store is None:
            raise HTTPException(status_code=404, detail="There is no store " + str(store_id))
        found, version = shop.latest_spec(session, store_id)
        if found is None:
            raise HTTPException(status_code=409, detail="This store has no spec yet")
        return store, found, version

    def refuse(error):
        detail = str(error)
        if error.extra:
            detail = {"message": str(error), **error.extra}
        return HTTPException(status_code=error.status_code, detail=detail)

    @app.get("/stores/{store_id}/review")
    def store_review(store_id: int, session: DbSession):
        store, found, _version = store_and_spec(session, store_id)
        return review.review_payload(session, store, found)

    @app.patch("/stores/{store_id}/items/{item_id}")
    def patch_item(store_id: int, item_id: str, body: ItemPatch, session: DbSession):
        store, found, version = store_and_spec(session, store_id)
        changes = {}
        for field in ("name", "description", "unit_price", "category", "stock", "published"):
            if field in body.model_fields_set:
                changes[field] = getattr(body, field)
        try:
            found = review.edit_item(
                session, paypal, store, found, version, item_id, changes, body.resolve,
            )
        except review.ReviewError as error:
            session.rollback()
            raise refuse(error) from error
        return review.review_payload(session, store, found)

    @app.post("/stores/{store_id}/publish")
    def publish_items(store_id: int, body: PublishRequest, session: DbSession):
        store, found, _version = store_and_spec(session, store_id)
        try:
            review.set_published(session, store, found, body.item_ids, body.published)
        except review.ReviewError as error:
            session.rollback()
            raise refuse(error) from error
        return review.review_payload(session, store, found)

    @app.put("/stores/{store_id}/order")
    def order_items(store_id: int, body: OrderOfItems, session: DbSession):
        store, found, _version = store_and_spec(session, store_id)
        try:
            review.reorder(session, store, found, body.item_ids)
        except review.ReviewError as error:
            session.rollback()
            raise refuse(error) from error
        return review.review_payload(session, store, found)

    @app.put("/stores/{store_id}/columns/{field}")
    def rename_column(store_id: int, field: str, body: LabelRequest, session: DbSession):
        store, found, _version = store_and_spec(session, store_id)
        try:
            review.set_label(session, store, field, body.label)
        except review.ReviewError as error:
            session.rollback()
            raise refuse(error) from error
        return review.review_payload(session, store, found)

    # ---- buying ----

    @app.post("/stores/{store_id}/orders", status_code=201)
    def create_order(store_id: int, body: OrderRequest, session: DbSession):
        try:
            order, _quote = shop.buy(
                session, paypal, settings.buyer_vault_id, store_id, body.item_id,
                body.variant_id, body.add_on_ids, body.quantity, created_by="manual",
            )
        except OrderError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        if order["status"] != "captured":
            # the attempt is saved and shows in the orders grid, but it isn't a success
            raise HTTPException(status_code=502, detail={"message": order["error"],
                                                         "order": order})
        return order

    @app.get("/orders")
    def orders(session: DbSession):
        return {"orders": shop.list_orders(session, check)}

    # ---- Check and Defend, passed through to the Check service ----

    def merchant_check():
        # the Check client, for a route that needs the merchant side of it
        if check is None:
            raise HTTPException(status_code=503, detail="CHECK_URL isn't set on the API")
        if not check.can_read:
            raise HTTPException(status_code=503, detail="CHECK_MERCHANT_KEY isn't set on the API")
        return check

    def check_failure(error):
        # Check's own 4xx goes back as it is, so the page can say "already submitted" and the
        # like. a 401 means our key is wrong, which is our problem, not the caller's
        if error.status_code in (404, 409, 422, 429):
            return HTTPException(status_code=error.status_code, detail=str(error))
        return HTTPException(status_code=502, detail="Check: " + str(error))

    def session_token_from(authorization):
        # "Bearer <token>", the same header the Check dashboard sends its own API
        scheme, _, token = (authorization or "").partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Log in to review an order")
        return token

    @app.post("/auth/session")
    def log_in(body: LoginRequest):
        # the merchant's login is Check's dashboard login: one password for both apps. we only
        # pass it along and hand back the session Check made, nothing is kept here
        if check is None:
            raise HTTPException(status_code=503, detail="CHECK_URL isn't set on the API")
        try:
            made = check.create_session(body.password)
        except CheckError as error:
            if error.status_code == 401:
                raise HTTPException(status_code=401, detail="Wrong password") from error
            raise check_failure(error) from error
        return {"session_token": made["session_token"], "expires_at": made.get("expires_at")}

    @app.post("/orders/{order_id}/review-link", status_code=201)
    def review_link(order_id: int, session: DbSession,
                    authorization: Annotated[str | None, Header()] = None):
        # the confirm page for an order on hold, behind the merchant's login. it never approves
        # or rejects anything itself: the decision is made on the confirm page, so Check times
        # it the same way as on the buyer's phone. every call makes a new link and kills the
        # one before, so the frontend only asks when someone clicks
        token = session_token_from(authorization)
        if check is None:
            raise HTTPException(status_code=503, detail="CHECK_URL isn't set on the API")
        if not settings.check_frontend_url:
            raise HTTPException(status_code=503,
                                detail="CHECK_FRONTEND_URL isn't set on the API")
        order = shop.get_order(session, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="There is no order " + str(order_id))
        if order.check_order_id is None:
            raise HTTPException(status_code=409, detail="This order didn't go through Check")
        try:
            link = check.create_review_link(order.check_order_id, token)
        except CheckError as error:
            if error.status_code == 401:
                # Check didn't take the session: expired, or made before its key changed
                raise HTTPException(
                    status_code=401, detail="Your login has expired, log in again"
                ) from error
            raise check_failure(error) from error
        return {
            "url": settings.check_frontend_url + "/confirm/" + link["review_token"],
            "expires_at": link.get("expires_at"),
        }

    @app.get("/check/stats")
    def check_stats():
        # just the rubber-stamp bits of Check's /stats, for the strip above the orders grid.
        # merchant only, like Check keeps it, so the agent can't time its orders around it
        client = merchant_check()
        try:
            stats = client.get_stats()
        except CheckError as error:
            raise check_failure(error) from error
        return {
            "rubber_stamp_active": bool(stats.get("rubber_stamp_active")),
            "fast_streak": stats.get("fast_streak") or 0,
            "fast_threshold_ms": stats.get("fast_threshold_ms"),
            "median_decision_ms": stats.get("median_decision_ms"),
            # every order Check has, demo page orders included, for the line under the Orders
            # header that explains why Check shows more than this grid
            "check_total_orders": stats.get("total_orders"),
        }

    @app.get("/orders/agent-stats")
    def agent_stats(session: DbSession):
        # how often Check holds each agent's orders, from our own orders table
        rows = list(session.execute(select(Order).order_by(Order.id)).scalars())
        agents = held_rates(rows)
        for agent_row in agents:
            agent_row["label"] = AGENT_LABELS.get(agent_row["created_by"],
                                                  agent_row["created_by"])
        return {"agents": agents}

    @app.get("/disputes")
    def disputes():
        client = merchant_check()
        try:
            return {"disputes": client.list_disputes()}
        except CheckError as error:
            raise check_failure(error) from error

    @app.post("/disputes/sync")
    def sync_disputes():
        client = merchant_check()
        try:
            return client.sync_disputes()
        except CheckError as error:
            raise check_failure(error) from error

    @app.get("/disputes/{dispute_id}/evidence")
    def dispute_evidence(dispute_id: int):
        client = merchant_check()
        try:
            return client.dispute_evidence(dispute_id)
        except CheckError as error:
            raise check_failure(error) from error

    @app.post("/disputes/{dispute_id}/redraft")
    def redraft_dispute(dispute_id: int):
        client = merchant_check()
        try:
            return client.redraft_dispute(dispute_id)
        except CheckError as error:
            raise check_failure(error) from error

    @app.post("/disputes/{dispute_id}/submit-evidence")
    def submit_dispute_evidence(dispute_id: int):
        client = merchant_check()
        try:
            return client.submit_dispute_evidence(dispute_id)
        except CheckError as error:
            raise check_failure(error) from error

    # ---- the demo shopping agent ----

    @app.post("/agent/chat")
    def agent_chat(body: ChatRequest, session: DbSession):
        if body.messages[-1].role != "user":
            raise HTTPException(status_code=400, detail="The last message has to be the user's")
        if agent_client is None and not settings.anthropic_api_key:
            raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY isn't set on the API")
        if body.sloppy and check is None:
            # without Check the wrong size would just be paid for, with nobody to catch it
            raise HTTPException(
                status_code=400,
                detail="The sloppy agent only works with CHECK_URL set, so Check can hold "
                "the wrong order",
            )

        agent_options = {"client": agent_client, "check": check, "sloppy": body.sloppy}
        if order_reader is not None:
            agent_options["order_reader"] = order_reader
        agent = ShoppingAgent(session, paypal, settings, **agent_options)
        history = [message.model_dump() for message in body.messages]
        try:
            return agent.chat(history)
        except Exception as error:  # noqa: BLE001
            logger.exception("Agent chat failed")
            raise HTTPException(
                status_code=502, detail="The Claude call failed: " + describe_ai_error(error)
            ) from error

    # ---- demo ----

    @app.post("/demo/reset", status_code=202)
    def demo_reset(session: DbSession, body: ResetRequest | None = None):
        if connect.runs_in_progress() > 0:
            raise HTTPException(
                status_code=409, detail="A store is still connecting, wait for it to finish"
            )
        mode = (body.mode if body else None) or settings.demo_mode

        shop.wipe_everything(session)
        bus.clear()

        started = []
        for url in demo_store_urls():
            store = begin_connect(session, url, mode)
            started.append({"store_id": store.id, "url": url})
        return {"mode": mode, "stores": started}

    return app


def app_factory():
    # uvicorn backend.app.main:app_factory --factory
    return create_app()
