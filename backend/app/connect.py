# One connect run: URL -> page text -> spec (Claude) -> verify every item (fixed code + real
# PayPal sandbox orders) -> store is live. Runs in a background thread and reports every step
# on the event bus, which the SSE endpoint streams to the browser.
#
# Whatever goes wrong ends in an "error" event with the reason and a failed store. There is no
# fallback spec and no pretend success.

import logging
import threading

from backend.app import models, review, shop
from backend.app.config import allowed_fetch_hosts
from backend.app.demo import RecordingAI, ReplayAI, load_fixture, slug_for_url
from backend.app.events import bus
from backend.app.extractor import ClaudeExtractor, ExtractionError
from backend.app.fetcher import FetchError, fetch_page
from backend.app.models import VerificationRun
from backend.app.spec import SpecError
from backend.app.verifier import describe_ai_error, verify_store

logger = logging.getLogger(__name__)

# a public demo shouldn't let one visitor start fifty runs at once
MAX_RUNS_AT_ONCE = 4

# what the merchant sees when Claude's spec fails validation. the validation message itself
# ("items: List should have at least 1 item after validation, not 0") goes in the Live steps log
NO_PRODUCTS_MESSAGE = (
    "We couldn't find any products with prices on this page, so nothing was published."
)
UNREADABLE_SPEC_MESSAGE = (
    "We couldn't read the products on this page clearly enough, so nothing was published."
)

running = set()
running_lock = threading.Lock()


def runs_in_progress():
    with running_lock:
        return len(running)


def claim_run(store_id):
    with running_lock:
        if len(running) >= MAX_RUNS_AT_ONCE:
            return False
        running.add(store_id)
        return True


def release_run(store_id):
    with running_lock:
        running.discard(store_id)


class Recorder:
    # what the verify loop uses to write to the database
    def __init__(self, session, store_id):
        self.session = session
        self.store_id = store_id

    def save_run(self, item_id, attempt, version, result):
        self.session.add(VerificationRun(
            store_id=self.store_id,
            item_id=item_id,
            attempt=attempt,
            spec_version=version,
            page_check_ok=result.page_check_ok,
            paypal_check_ok=result.paypal_check_ok,
            paypal_order_id=result.paypal_order_id,
            ok=result.ok,
            reason=result.reason,
        ))
        self.session.commit()

    def save_spec(self, spec, note):
        return shop.save_spec(self.session, self.store_id, spec, note)


def default_ai_factory(settings):
    if not settings.anthropic_api_key:
        raise ExtractionError("ANTHROPIC_API_KEY isn't set on the API")
    return ClaudeExtractor(settings.anthropic_api_key)


def run_connect(store_id, url, mode, settings, paypal, session_factory,
                ai_factory=default_ai_factory, fetch=fetch_page):
    # the whole run. never raises, a failure becomes an "error" event
    session = session_factory()
    replay = mode == "replay"

    def emit(event_type, message, item_id=None, data=None):
        data = dict(data or {})
        # so the UI can label everything that came from a recorded fixture
        data["fixture"] = replay
        bus.emit(store_id, event_type, message, item_id, data)

    def fail(reason):
        store = session.get(models.Store, store_id)
        if store is not None:
            store.status = models.FAILED
            store.error = reason
            session.commit()
        emit("error", reason)

    try:
        recording = None

        # 1. the page
        if replay:
            fixture = load_fixture(url)
            if fixture is None:
                fail(
                    "Replay mode has no recorded fixture for " + slug_for_url(url)
                    + ". Connect it live instead, or record one."
                )
                return
            ai = ReplayAI(fixture, url)
            emit("fetch.started", "Loading the recorded page for " + url + " (FIXTURE).")
            page = ai.page()
        else:
            emit("fetch.started", "Fetching " + url + ".")
            try:
                page = fetch(url, allowed_fetch_hosts(settings.fetch_allow_hosts))
            except FetchError as error:
                fail(str(error) + ".")
                return
            ai = ai_factory(settings)
            if settings.record_fixtures:
                recording = RecordingAI(ai, url)
                ai = recording
        emit(
            "fetch.done",
            "Read " + str(len(page.text)) + " characters of page text.",
            data={"title": page.title, "characters": len(page.text)},
        )

        # 2. the spec
        emit("extract.started", "Claude is reading the page and writing the store spec.")
        try:
            spec = ai.extract_spec(page)
        except SpecError as error:
            # a validation message is for us, not the merchant. the real reason stays in the log
            emit("extract.rejected", "Claude's spec was rejected: " + str(error) + ".")
            fail(friendly_spec_error(error))
            return
        except ExtractionError as error:
            # these are already plain sentences, like "Claude declined to read this page"
            fail("Claude's spec was rejected: " + str(error) + ".")
            return
        except Exception as error:  # noqa: BLE001
            logger.exception("Extraction failed for store %s", store_id)
            fail("The Claude call failed: " + describe_ai_error(error) + ".")
            return

        version = shop.save_spec(session, store_id, spec, "First extraction")
        store = session.get(models.Store, store_id)
        store.merchant_name = spec.merchant.name
        session.commit()
        emit(
            "extract.done",
            "Claude found " + str(len(spec.items)) + " items at " + spec.merchant.name + ".",
            data={"item_count": len(spec.items), "spec": spec.model_dump(), "version": version},
        )

        # 3. verify, one item at a time
        spec, counts = verify_store(
            store_id, spec, version, page.text, ai, paypal, emit, Recorder(session, store_id)
        )

        # 4. done. live means at least one item can really be bought
        store = session.get(models.Store, store_id)
        if counts["verified"] > 0:
            store.status = models.LIVE
        else:
            store.status = models.FAILED
            store.error = "No item passed verification"
        session.commit()
        # the merchant's review rows: clean verified items go live, flagged ones wait
        review.ensure_reviews(session, store, spec)

        if recording is not None and counts["verified"] > 0:
            recording.save()

        if counts["verified"] > 0:
            message = (
                spec.merchant.name + " is agent-ready: " + str(counts["verified"])
                + " verified, " + str(counts["failed"]) + " failed, "
                + str(counts["unavailable"]) + " unavailable."
            )
        else:
            message = (
                spec.merchant.name + " is not live, no item passed verification ("
                + str(counts["failed"]) + " failed, " + str(counts["unavailable"])
                + " unavailable)."
            )
        emit(
            "store.ready",
            message,
            data={"counts": counts, "status": store.status, "spec": spec.model_dump()},
        )
    except Exception as error:  # noqa: BLE001
        logger.exception("Connect run crashed for store %s", store_id)
        session.rollback()
        fail("The connect run crashed: " + describe_ai_error(error) + ".")
    finally:
        session.close()
        release_run(store_id)


def friendly_spec_error(error):
    # parse_spec keeps pydantic's error as the cause, so this looks at the real problem and not
    # at its wording. a page with nothing for sale (example.com) comes back with no items
    cause = error.__cause__
    if hasattr(cause, "errors"):
        for problem in cause.errors():
            if tuple(problem["loc"]) == ("items",) and problem["type"] == "too_short":
                return NO_PRODUCTS_MESSAGE
    return UNREADABLE_SPEC_MESSAGE


def start_connect(store_id, url, mode, settings, paypal, session_factory,
                  ai_factory=default_ai_factory, fetch=fetch_page):
    thread = threading.Thread(
        target=run_connect,
        args=(store_id, url, mode, settings, paypal, session_factory, ai_factory, fetch),
        name="connect-" + str(store_id),
        daemon=True,
    )
    thread.start()
    return thread
