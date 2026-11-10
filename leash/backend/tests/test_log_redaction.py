# Review tokens can't end up in the access log. The last test runs a real uvicorn, since what
# matters is what the server writes, and the order uvicorn sets up logging in is the risky part.
# It's slow, so a plain pytest skips it. Run it with: pytest -m real_server

import logging
import os
import socket
import subprocess
import sys
import time

import pytest
import requests

from backend.app.log_redaction import RedactReviewTokens, redact_review_tokens

TOKEN = "kL0xN3vQpZ8sT1uYwB6cD4eF7gH2iJ9mO5aR-_stuvw"


def access_record(path):
    # the shape uvicorn logs: the path is an argument, not part of the message
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, "h11_impl.py", 1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:50000", "GET", path, "1.1", 200),
        None,
    )


@pytest.mark.parametrize(("path", "expected"), [
    ("/review/" + TOKEN, "/review/[redacted]"),
    ("/review/" + TOKEN + "/approve", "/review/[redacted]/approve"),
    ("/review/" + TOKEN + "/reject", "/review/[redacted]/reject"),
    ("/review/" + TOKEN + "/opened", "/review/[redacted]/opened"),
    ("/review/" + TOKEN + "?utm=1", "/review/[redacted]?utm=1"),
    ("/review/" + TOKEN + "/approve?x=1", "/review/[redacted]/approve?x=1"),
])
def test_token_is_redacted_and_the_rest_of_the_line_survives(path, expected):
    record = access_record(path)

    assert RedactReviewTokens().filter(record) is True

    message = record.getMessage()
    assert TOKEN not in message
    assert message == '127.0.0.1:50000 - "GET ' + expected + ' HTTP/1.1" 200'


@pytest.mark.parametrize("path", ["/orders", "/orders/1/review-link", "/health", "/agent/orders/1"])
def test_other_paths_are_left_alone(path):
    record = access_record(path)

    RedactReviewTokens().filter(record)

    assert path in record.getMessage()


def test_token_in_the_message_itself_is_redacted_too():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "x.py", 1, "GET /review/" + TOKEN, None, None
    )

    RedactReviewTokens().filter(record)

    assert record.getMessage() == "GET /review/[redacted]"


def test_record_with_odd_args_doesnt_break_logging():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "x.py", 1, "no args at all", None, None
    )

    assert RedactReviewTokens().filter(record) is True
    assert record.getMessage() == "no args at all"


def test_importing_the_app_installs_the_filter():
    import backend.app.main  # noqa: F401

    assert redact_review_tokens in logging.getLogger("uvicorn.access").filters


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.real_server
def test_real_uvicorn_never_logs_a_token_and_keeps_access_logs_on(tmp_path):
    port = free_port()
    base = "http://127.0.0.1:" + str(port)
    log_path = tmp_path / "server.log"

    env = dict(os.environ)
    # never the real database, and no tables needed: the requests can fail, it's the log we want
    env["DATABASE_URL"] = "sqlite:///" + str(tmp_path / "empty.db")
    env["PYTHONUNBUFFERED"] = "1"

    with open(log_path, "w", encoding="utf-8") as log:
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.app.main:app",
             "--host", "127.0.0.1", "--port", str(port)],
            stdout=log, stderr=subprocess.STDOUT, env=env,
        )
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    if requests.get(base + "/health", timeout=2).ok:
                        break
                except requests.RequestException:
                    pass
                assert time.monotonic() < deadline, "server never came up"
                time.sleep(0.2)

            requests.get(base + "/review/" + TOKEN, timeout=10)
            requests.post(base + "/review/" + TOKEN + "/opened", timeout=10)
            requests.post(base + "/review/" + TOKEN + "/approve", json={}, timeout=10)
            requests.post(base + "/review/" + TOKEN + "/reject?why=1", json={}, timeout=10)
        finally:
            server.terminate()
            server.wait(timeout=15)

    output = log_path.read_text(encoding="utf-8")
    assert TOKEN not in output
    # still logging, with the parts worth having
    assert '"GET /health HTTP/1.1" 200' in output
    assert '"GET /review/[redacted] HTTP/1.1"' in output
    assert '"POST /review/[redacted]/opened HTTP/1.1"' in output
    assert '"POST /review/[redacted]/approve HTTP/1.1"' in output
    assert '"POST /review/[redacted]/reject?why=1 HTTP/1.1"' in output
