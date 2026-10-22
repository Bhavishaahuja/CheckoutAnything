# Small PayPal REST client. only wraps what spikes/ proved works in sandbox:
#   OAuth token, Orders v2 create/get/authorize, Payments v2 capture/void/get authorization.
#
# Endpoint shapes checked against the OpenAPI schemas (source of truth):
#   https://developer.paypal.com/api/orders/v2/schema.yaml    (v2.36)
#   https://developer.paypal.com/api/payments/v2/schema.yaml
#   token: https://developer.paypal.com/api/rest/authentication (access_token + expires_in)
#
# Every POST gets a fresh PayPal-Request-Id unless the caller passes one in, so a caller
# can store it and safely retry the exact same request.

import time
import uuid

import requests

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"

# refresh the token this many seconds before PayPal says it expires
TOKEN_EXPIRY_MARGIN_SECONDS = 60


class PayPalError(Exception):
    # PayPal error bodies look like:
    #   {"name": "UNPROCESSABLE_ENTITY", "message": "...", "debug_id": "...",
    #    "details": [{"issue": "AUTHORIZATION_EXPIRED", "description": "..."}]}
    # debug_id is what PayPal support asks for, always log it

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
            return cls(response.status_code, message=response.text)

        # token errors use OAuth style {"error": ..., "error_description": ...}
        name = body.get("name") or body.get("error")
        message = body.get("message") or body.get("error_description")
        details = body.get("details") or []

        # first issue is the useful one, e.g. AUTHORIZATION_EXPIRED
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


class PayPalClient:
    def __init__(self, client_id, client_secret, base_url=SANDBOX_BASE_URL, timeout=30,
                 session=None):
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

        response = self.session.post(
            self.base_url + "/v1/oauth2/token",
            auth=(self.client_id, self.client_secret),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "PayPal-Request-Id": str(uuid.uuid4()),
            },
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
            # full object back, we need payment_source.paypal.attributes.vault etc
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
        # any 2xx is fine: authorize can be 200/201/202/207, void is 200 or 204
        if response.status_code < 200 or response.status_code >= 300:
            raise PayPalError.from_response(response)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    # ---- Orders v2 ----

    def create_order(self, order_body, request_id=None):
        # POST /v2/checkout/orders. order_body is the full Orders v2 request
        # (intent AUTHORIZE, purchase_units, payment_source), see spikes/
        return self._post("/v2/checkout/orders", order_body, request_id)

    def get_order(self, order_id):
        return self._get("/v2/checkout/orders/" + order_id)

    def authorize_order(self, order_id, request_id=None):
        # only needed after a buyer approves in the browser. a vault_id order comes back
        # already authorized from create_order (spike 2), don't call this on it
        return self._post("/v2/checkout/orders/" + order_id + "/authorize", {}, request_id)

    # ---- Payments v2 ----

    def capture_authorization(self, authorization_id, request_id=None):
        # empty body captures the full authorized amount
        return self._post(
            "/v2/payments/authorizations/" + authorization_id + "/capture", {}, request_id
        )

    def void_authorization(self, authorization_id, request_id=None):
        # returns the voided authorization (200) or None (204)
        return self._post(
            "/v2/payments/authorizations/" + authorization_id + "/void", None, request_id
        )

    def get_authorization(self, authorization_id):
        return self._get("/v2/payments/authorizations/" + authorization_id)

    def get_capture(self, capture_id):
        # a captured authorization reads CAPTURED, the capture itself reads COMPLETED
        return self._get("/v2/payments/captures/" + capture_id)


def client_from_settings(settings):
    return PayPalClient(
        settings.paypal_client_id,
        settings.paypal_client_secret,
        base_url=settings.paypal_base_url,
    )


def first_authorization(order):
    # authorizations live at purchase_units[0].payments.authorizations[0].
    # None if the order hasn't been authorized
    purchase_units = order.get("purchase_units") or []
    if not purchase_units:
        return None
    authorizations = (purchase_units[0].get("payments") or {}).get("authorizations") or []
    if not authorizations:
        return None
    return authorizations[0]
