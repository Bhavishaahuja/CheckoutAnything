# Small PayPal REST client, adapted from the Leash repo's client. Sandbox only.
# Wraps: OAuth token (cached), Orders v2 create / get / capture.
#
# Endpoint shapes checked against the OpenAPI schema (source of truth) on 2026-11-10:
#   https://developer.paypal.com/api/orders/v2/schema.yaml    (v2.36)
#   https://developer.paypal.com/api/payment-tokens/save-without-purchase/paypal
#     ("4. Use saved payment token": create with payment_source.paypal.vault_id and intent
#      CAPTURE comes back COMPLETED with the capture already in it, no /capture call)
#   https://developer.paypal.com/api/orders-v2/save-with-purchase/paypal   (getting a vault id)
#   token: https://developer.paypal.com/api/rest/authentication
#
# Every POST gets a fresh PayPal-Request-Id unless the caller passes one in. PayPal requires
# one whenever the create call carries a payment_source (PAYPAL_REQUEST_ID_REQUIRED).

import time
import uuid
from decimal import Decimal

import requests

from backend.app.config import SANDBOX_BASE_URL

# refresh the token this many seconds before PayPal says it expires
TOKEN_EXPIRY_MARGIN_SECONDS = 60

class PayPalError(Exception):
    # PayPal error bodies look like:
    #   {"name": "UNPROCESSABLE_ENTITY", "message": "...", "debug_id": "...",
    #    "details": [{"issue": "AMOUNT_MISMATCH", "description": "..."}]}
    # debug_id is what PayPal support asks for, always keep it

    def __init__(self, status_code, name=None, message=None, issue=None, debug_id=None,
                 details=None):
        self.status_code = status_code
        self.name = name
        self.message = message
        self.issue = issue
        self.debug_id = debug_id
        self.details = details or []
        super().__init__(
            str(status_code) + " " + str(name) + " issue=" + str(issue)
            + " debug_id=" + str(debug_id) + ": " + str(message)
        )

    @classmethod
    def from_response(cls, response):
        try:
            body = response.json()
        except ValueError:
            return cls(response.status_code, message=response.text[:300])

        # token errors use OAuth style {"error": ..., "error_description": ...}
        name = body.get("name") or body.get("error")
        message = body.get("message") or body.get("error_description")
        details = body.get("details") or []

        # first issue is the useful one, e.g. AMOUNT_MISMATCH
        issue = None
        for detail in details:
            if detail.get("issue"):
                issue = detail["issue"]
                break

        return cls(
            response.status_code,
            name=name,
            message=message,
            issue=issue,
            debug_id=body.get("debug_id"),
            details=details,
        )


# timeouts and dropped connections come through as requests errors, not PayPalError
PAYPAL_FAILURES = (PayPalError, requests.RequestException)


def describe_failure(error):
    # one human sentence for the UI, with the debug id when PayPal gave one
    if isinstance(error, PayPalError):
        text = "PayPal said " + str(error.issue or error.name or error.status_code)
        if error.message:
            text += ": " + str(error.message)
        if error.debug_id:
            text += " (debug id " + str(error.debug_id) + ")"
        return text
    return "Couldn't reach PayPal: " + type(error).__name__


class PayPalClient:
    def __init__(self, client_id, client_secret, base_url=SANDBOX_BASE_URL, timeout=30,
                 session=None):
        if base_url.rstrip("/") != SANDBOX_BASE_URL:
            raise ValueError("This app only talks to the PayPal sandbox")
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self._token = None
        self._token_expires_at = 0.0

    # ---- auth ----

    def get_token(self):
        # reuse the cached token until it's about to expire
        if self._token and time.time() < self._token_expires_at:
            return self._token

        if not self.client_id or not self.client_secret:
            raise PayPalError(
                401, name="NOT_CONFIGURED",
                message="PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET aren't set on the API",
            )

        response = self.session.post(
            self.base_url + "/v1/oauth2/token",
            auth=(self.client_id, self.client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise PayPalError.from_response(response)

        body = response.json()
        self._token = body["access_token"]
        expires_in = body.get("expires_in", 0)
        self._token_expires_at = time.time() + expires_in - TOKEN_EXPIRY_MARGIN_SECONDS
        return self._token

    # ---- plumbing ----

    def _headers(self):
        return {
            "Authorization": "Bearer " + self.get_token(),
            "Content-Type": "application/json",
            # the default is a minimal body (id, status, links). we need the whole order
            "Prefer": "return=representation",
        }

    def _get(self, path):
        response = self.session.get(
            self.base_url + path, headers=self._headers(), timeout=self.timeout
        )
        return self._handle(response)

    def _post(self, path, json_body=None, request_id=None):
        headers = self._headers()
        headers["PayPal-Request-Id"] = request_id or str(uuid.uuid4())
        response = self.session.post(
            self.base_url + path, headers=headers, json=json_body, timeout=self.timeout
        )
        return self._handle(response)

    def _handle(self, response):
        if response.status_code < 200 or response.status_code >= 300:
            raise PayPalError.from_response(response)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    # ---- Orders v2 ----

    def create_order(self, order_body, request_id=None):
        # POST /v2/checkout/orders. order_body is the full Orders v2 request
        return self._post("/v2/checkout/orders", order_body, request_id)

    def get_order(self, order_id):
        return self._get("/v2/checkout/orders/" + order_id)

    def capture_order(self, order_id, request_id=None):
        # only for an order a buyer approved in the browser (setup_vault.py). an order paid
        # with a vault_id comes back already captured from create_order
        return self._post("/v2/checkout/orders/" + order_id + "/capture", {}, request_id)


def client_from_settings(settings):
    return PayPalClient(
        settings.paypal_client_id,
        settings.paypal_client_secret,
        base_url=settings.paypal_base_url,
    )


# ---- building and reading orders ----


def money(currency, value):
    # value is a Decimal or a "9.00" string. PayPal wants a string with 2 decimals
    return {"currency_code": currency, "value": str(Decimal(value).quantize(Decimal("0.01")))}


def build_order_body(currency, item_name, unit_amount, quantity, shipping_amount,
                     description=None, custom_id=None, vault_id=None):
    # one purchase unit with one line item. field names are from the Orders v2 schema:
    # items[].name / quantity (a string) / unit_amount, and amount.breakdown.item_total,
    # which is required once an item has a unit_amount.
    #   item_total has to equal unit_amount * quantity        (else ITEM_TOTAL_MISMATCH)
    #   amount has to equal item_total + shipping             (else AMOUNT_MISMATCH)
    unit_amount = Decimal(unit_amount)
    shipping_amount = Decimal(shipping_amount)
    item_total = unit_amount * quantity
    total = item_total + shipping_amount

    line_item = {
        "name": item_name,
        "quantity": str(quantity),
        "unit_amount": money(currency, unit_amount),
    }
    if description:
        line_item["description"] = description

    breakdown = {"item_total": money(currency, item_total)}
    if shipping_amount > 0:
        breakdown["shipping"] = money(currency, shipping_amount)

    amount = money(currency, total)
    amount["breakdown"] = breakdown

    purchase_unit = {"amount": amount, "items": [line_item]}
    if custom_id:
        purchase_unit["custom_id"] = custom_id

    body = {"intent": "CAPTURE", "purchase_units": [purchase_unit]}
    if vault_id:
        # the saved wallet. nobody is there to click anything, so say the merchant started it
        body["payment_source"] = {
            "paypal": {
                "vault_id": vault_id,
                "stored_credential": {
                    "payment_initiator": "MERCHANT",
                    "usage": "SUBSEQUENT",
                    "usage_pattern": "IMMEDIATE",
                },
            }
        }
    return body


def first_purchase_unit(order):
    purchase_units = (order or {}).get("purchase_units") or []
    if not purchase_units:
        return {}
    return purchase_units[0]


def first_capture(order):
    # captures live at purchase_units[0].payments.captures[0]. None if nothing was captured
    captures = (first_purchase_unit(order).get("payments") or {}).get("captures") or []
    if not captures:
        return None
    return captures[0]
