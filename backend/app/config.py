# settings come from env vars (or .env locally). names match .env.example

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# the one fictional store Leash runs for. not env vars, these never change between deploys
STORE_NAME = "Fernwood Supply Co"
# what shoppers actually call it. "from Fernwood" shouldn't send a clean order to review
STORE_ALIASES = ["fernwood", "fernwood supply", "fernwood supply co"]

# every Claude call in the app uses this, so a model bump only happens here
CLAUDE_MODEL = "claude-sonnet-5-5"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # PayPal sandbox app
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"
    paypal_webhook_id: str = ""
    # where PayPal sends the buyer after approving (or cancelling) an order with no vault id.
    # placeholders until the confirm page exists
    paypal_return_url: str = "https://example.com/return"
    paypal_cancel_url: str = "https://example.com/cancel"

    # sandbox logins, only used by scripts and the demo
    sandbox_merchant_email: str = ""
    sandbox_buyer_email: str = ""

    anthropic_api_key: str = ""

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/leash"

    # deployed frontend, on top of the Vite dev server which is always allowed
    frontend_origin: str = ""

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url):
        # Render hands out postgres:// or postgresql:// URLs. SQLAlchemy reads those as
        # psycopg2, but we install psycopg (v3), so point it at the right driver
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url


@lru_cache
def get_settings():
    return Settings()
