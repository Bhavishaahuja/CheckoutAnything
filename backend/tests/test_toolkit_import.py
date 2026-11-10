# The Agent Toolkit is installed with --no-deps, so pip never checks that the modules it
# imports are there. This imports it the same way backend/app/toolkit.py does, so a missing
# one (httpx was the first) fails here and not on the hosted API.

import importlib.util

import pytest

from backend.app import toolkit


def test_agent_toolkit_imports():
    # skip only when the package isn't installed at all. installed but broken has to fail
    if importlib.util.find_spec("paypal_agent_toolkit") is None:
        pytest.skip("paypal-agent-toolkit isn't installed")

    from paypal_agent_toolkit.shared.api import PayPalAPI
    from paypal_agent_toolkit.shared.configuration import Context

    assert PayPalAPI is not None
    assert Context is not None


def test_import_failure_names_the_missing_module(monkeypatch):
    # None in sys.modules makes the import fail, like a module that isn't installed
    import sys

    monkeypatch.setitem(sys.modules, "paypal_agent_toolkit.shared.api", None)

    with pytest.raises(toolkit.ToolkitError) as caught:
        toolkit.get_order_details("id", "secret", "ORDER-1")

    message = str(caught.value)
    assert "couldn't be imported" in message
    assert "paypal_agent_toolkit.shared.api" in message
