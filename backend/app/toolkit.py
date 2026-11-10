# The PayPal Agent Toolkit (github.com/paypal/agent-toolkit, Apache-2.0), used by the shopping
# agent to read an order straight from PayPal after buying.
#
# What it can and can't do for us (checked against its Python source, v1.11.0):
#   - it has no vault or payment token support at all. create_order only builds an order a
#     buyer has to approve in a browser, and pay_order only captures after that approval.
#     so the agent's payment goes through our own buy endpoint (orders.place_order)
#   - get_order_details reads an order, which is what we use here
#   - there is no Claude integration in the Python package, so we call its plain
#     PayPalAPI.run(method, params) entry point and hand the result to Claude ourselves
#   - Context() defaults to LIVE. we always pass sandbox=True
#
# It's installed with --no-deps (see the README): the package pins old versions of
# openai-agents, langchain and crewai-tools that this app never imports.

import json


class ToolkitError(Exception):
    pass


def get_order_details(client_id, client_secret, paypal_order_id):
    # returns {"status", "amount", "capture_id", "capture_status"} read by the Toolkit
    try:
        from paypal_agent_toolkit.shared.api import PayPalAPI
        from paypal_agent_toolkit.shared.configuration import Context
    except ImportError as error:
        raise ToolkitError(
            "The PayPal Agent Toolkit isn't installed on the API "
            "(pip install --no-deps paypal-agent-toolkit)"
        ) from error

    if not client_id or not client_secret:
        raise ToolkitError("PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET aren't set on the API")

    try:
        api = PayPalAPI(client_id=client_id, secret=client_secret, context=Context(sandbox=True))
        answer = json.loads(api.run("get_order_details", {"order_id": paypal_order_id}))
    except Exception as error:  # noqa: BLE001
        # the Toolkit raises plain requests / RuntimeError / pydantic errors
        raise ToolkitError(
            "The Toolkit couldn't read the order: " + type(error).__name__
        ) from error

    return summarize_order_details(answer)


def summarize_order_details(answer):
    # the Toolkit's "message" always says "successfully captured" whatever the real state is,
    # so read status and the raw order instead
    raw = answer.get("raw") or {}
    capture = {}
    purchase_units = raw.get("purchase_units") or []
    if purchase_units:
        captures = (purchase_units[0].get("payments") or {}).get("captures") or []
        if captures:
            capture = captures[0]
    return {
        "source": "PayPal Agent Toolkit get_order_details",
        "status": answer.get("status"),
        "amount": answer.get("amount"),
        "capture_id": capture.get("id"),
        "capture_status": capture.get("status"),
    }
