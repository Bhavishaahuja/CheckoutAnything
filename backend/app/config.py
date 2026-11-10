# settings come from env vars (or .env locally). names match .env.example

import logging
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# every Claude call in the app uses this, so a model bump only happens here
CLAUDE_MODEL = "claude-sonnet-5-5"

# the three fictional demo stores, in the order /demo/reset connects them.
# the slug is the folder name under demo-stores/ and the fixture file name
DEMO_STORE_SLUGS = ["fernwood-thistle-goods", "quill-pipkin-studio", "hollowbrook-bakery"]

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # PayPal sandbox app
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_base_url: str = SANDBOX_BASE_URL
    # the saved sandbox buyer wallet the buy endpoint pays with (backend/scripts/setup_vault.py)
    buyer_vault_id: str = ""

    anthropic_api_key: str = ""

    # sqlite so a fresh clone runs with no database to install. Render sets a Postgres URL
    database_url: str = "sqlite:///./checkout_anything.db"

    # which sites' browsers may call the API, comma-separated. never a wildcard
    frontend_origins: str = "http://localhost:5173"

    # where the three demo stores are hosted, /demo/reset connects <base>/<slug>/
    demo_stores_base_url: str = "http://localhost:5174"

    # "live" reads the page and calls Claude. "replay" replays recorded fixtures instead
    # (PayPal calls still run for real). the UI toggle can override this per connect
    demo_mode: str = "live"
    # set to 1 while doing live runs to save them as fixtures in backend/fixtures
    record_fixtures: bool = False

    # local dev only: host:port pairs the fetcher may read even though they are private
    # addresses, like localhost:5174 for the demo stores. leave empty on a hosted deploy
    fetch_allow_hosts: str = ""

    @field_validator("paypal_base_url")
    @classmethod
    def sandbox_only(cls, url):
        # hard rule: this app never talks to live PayPal
        if url.rstrip("/") != SANDBOX_BASE_URL:
            raise ValueError("PAYPAL_BASE_URL has to be the sandbox, " + SANDBOX_BASE_URL)
        return url.rstrip("/")

    @field_validator("demo_mode")
    @classmethod
    def known_demo_mode(cls, mode):
        mode = mode.strip().lower()
        if mode not in ("live", "replay"):
            raise ValueError("DEMO_MODE has to be live or replay")
        return mode

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url):
        if not url.strip():
            # DATABASE_URL= left blank in .env means the local sqlite file
            return "sqlite:///./checkout_anything.db"
        # Render hands out postgres:// or postgresql:// URLs. SQLAlchemy reads those as
        # psycopg2, but we install psycopg (v3), so point it at the right driver
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url


def cors_origins(setting):
    # browsers send the origin with no trailing slash, so one left in here would never match.
    # a wildcard gets dropped: a mistyped env var shouldn't open the API to every site
    origins = []
    for origin in setting.split(","):
        origin = origin.strip().rstrip("/")
        if origin == "*":
            logger.warning("Ignoring * in FRONTEND_ORIGINS, list each site instead")
        elif origin:
            origins.append(origin)
    return origins


def allowed_fetch_hosts(setting):
    hosts = set()
    for host in setting.split(","):
        host = host.strip().lower()
        if host:
            hosts.add(host)
    return hosts


@lru_cache
def get_settings():
    return Settings()
