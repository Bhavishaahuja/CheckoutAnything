# Talks to the Check service (check/ in this repo), the part that holds an agent's payment
# until the order is shown to be what the human asked for. Shapes are from check/docs/api.md.
#
# Two keys, because Check keeps the two sides apart:
#   agent key     POST /mandates and POST /orders. all it gets back is where the order stands
#   merchant key  reading orders with the check result, review links and disputes
#
# Only used when CHECK_URL is set. With it unset, nothing in the app builds one of these.

import requests

# POST /orders waits for PayPal's hold, the check (a Claude call) and any auto-capture
ORDER_TIMEOUT = 90
READ_TIMEOUT = 30
# sync asks PayPal about every captured order, drafting and submitting call Claude or PayPal
DISPUTE_TIMEOUT = 90


class CheckError(Exception):
    # Check said no, or couldn't be reached. status_code is Check's own, 0 when there was none
    def __init__(self, message, status_code=0, detail=None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


def detail_message(detail):
    # Check's errors are {"detail": "text"}, {"detail": {"message": ...}} or FastAPI's
    # validation list
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    if isinstance(detail, list) and detail and isinstance(detail[0], dict):
        return str(detail[0].get("msg") or "The request wasn't valid")
    return None


class CheckClient:
    def __init__(self, base_url, agent_key="", merchant_key="", http=None):
        self.base_url = base_url.rstrip("/")
        self.agent_key = agent_key
        self.merchant_key = merchant_key
        self.http = http or requests

    @property
    def can_read(self):
        # without the merchant key an order still goes through Check, we just can't show why
        # it was held
        return bool(self.merchant_key)

    def _call(self, method, path, key, json_body=None, timeout=READ_TIMEOUT, params=None):
        if not key:
            raise CheckError("The key for this Check call isn't set on the API", 503)
        try:
            response = self.http.request(
                method, self.base_url + path, json=json_body, params=params,
                headers={"X-API-Key": key}, timeout=timeout,
            )
        except requests.RequestException as error:
            raise CheckError("Couldn't reach Check: " + type(error).__name__) from error

        if response.status_code == 204:
            return None
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code >= 400:
            detail = body.get("detail") if isinstance(body, dict) else None
            message = detail_message(detail) or "Check answered " + str(response.status_code)
            raise CheckError(message, response.status_code, detail)
        return body

    # ---- agent side ----

    def create_mandate(self, request_text, merchant, buyer_label):
        # the human's own words, verbatim. Check parses them into rules and keeps the text
        # as dispute evidence
        return self._call("POST", "/mandates", self.agent_key, {
            "buyer_label": buyer_label,
            "request_text": request_text,
            "merchant": merchant,
        }, timeout=ORDER_TIMEOUT)

    def create_order(self, mandate_id, items, shipping, vault_id, merchant):
        # returns {id, status, review_state, total} once Check has held, checked and decided
        return self._call("POST", "/orders", self.agent_key, {
            "mandate_id": mandate_id,
            "items": items,
            "shipping": shipping,
            "vault_id": vault_id,
            "merchant": merchant,
        }, timeout=ORDER_TIMEOUT)

    # ---- merchant side ----

    def get_order(self, order_id):
        return self._call("GET", "/orders/" + str(order_id), self.merchant_key)

    def list_orders(self, limit=200):
        return self._call("GET", "/orders", self.merchant_key, params={"limit": limit})

    def create_review_link(self, order_id):
        # {review_token, expires_at}. asking again kills the link made before
        return self._call(
            "POST", "/orders/" + str(order_id) + "/review-link", self.merchant_key
        )

    def list_disputes(self, limit=200):
        return self._call("GET", "/disputes", self.merchant_key, params={"limit": limit})

    def sync_disputes(self):
        return self._call(
            "POST", "/disputes/sync", self.merchant_key, timeout=DISPUTE_TIMEOUT
        )

    def dispute_evidence(self, dispute_id):
        return self._call(
            "GET", "/disputes/" + str(dispute_id) + "/evidence", self.merchant_key,
            timeout=DISPUTE_TIMEOUT,
        )

    def redraft_dispute(self, dispute_id):
        return self._call(
            "POST", "/disputes/" + str(dispute_id) + "/redraft", self.merchant_key,
            timeout=DISPUTE_TIMEOUT,
        )

    def submit_dispute_evidence(self, dispute_id):
        return self._call(
            "POST", "/disputes/" + str(dispute_id) + "/submit-evidence", self.merchant_key,
            timeout=DISPUTE_TIMEOUT,
        )


def client_from_settings(settings):
    # None when CHECK_URL isn't set, which is what keeps the old path the default
    if not settings.check_url:
        return None
    return CheckClient(settings.check_url, settings.check_agent_key, settings.check_merchant_key)
