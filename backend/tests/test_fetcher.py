# The fetcher against a real HTTP server on localhost, so the socket-level checks are
# exercised for real and not just against fakes.

import http.server
import threading

import pytest
import requests

from backend.app.fetcher import FetchError, connected_address, fetch_page, is_public_ip
from backend.tests.fakes import DEMO_STORES_DIR


class Handler(http.server.SimpleHTTPRequestHandler):
    # set per server below
    protocol_version = "HTTP/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DEMO_STORES_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/big":
            body = b"x" * (2 * 1024 * 1024 + 10)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            if self.protocol_version == "HTTP/1.1":
                # a kept-open connection has to say how long the body is. the HTTP/1.0
                # server doesn't, so that one tests the cap on a body of unknown length
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/empty":
            body = b"<html><body><script>render()</script></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/to-metadata":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, *args):
        pass


class KeepAliveHandler(Handler):
    protocol_version = "HTTP/1.1"


def start_server(handler):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture(scope="module", params=[Handler, KeepAliveHandler],
                ids=["connection-close", "keep-alive"])
def server(request):
    running = start_server(request.param)
    yield running
    running.shutdown()


@pytest.fixture
def session():
    # no proxy from the environment, these requests have to reach localhost directly
    plain = requests.Session()
    plain.trust_env = False
    return plain


def base(server):
    return "http://127.0.0.1:" + str(server.server_address[1])


def allowed(server):
    return {"127.0.0.1:" + str(server.server_address[1])}


def test_the_connected_address_can_be_read_before_the_body(server, session):
    # this is what the SSRF guard relies on. if it ever returns None, every fetch is refused
    response = session.get(base(server) + "/hollowbrook-bakery/", stream=True)
    try:
        assert connected_address(response) == "127.0.0.1"
    finally:
        response.close()


def test_an_allow_listed_page_is_fetched_and_turned_into_text(server, session):
    page = fetch_page(base(server) + "/hollowbrook-bakery/", allowed(server), session)
    assert page.title == "Hollowbrook Bakery - This Week's Menu"
    assert "| Seeded Rye caraway, sunflower, a little honey | ~~$8~~ $7" in page.text
    assert "font-family" not in page.text


def test_a_redirect_is_followed_by_hand(server, session):
    page = fetch_page(base(server) + "/hollowbrook-bakery", allowed(server), session)
    assert page.final_url.endswith("/hollowbrook-bakery/")
    assert "Sourdough Loaf" in page.text


def test_localhost_is_refused_without_the_allow_list(server, session):
    with pytest.raises(FetchError) as error:
        fetch_page(base(server) + "/hollowbrook-bakery/", None, session)
    assert "private" in str(error.value)


def test_a_redirect_to_an_internal_address_is_refused(server, session):
    # the first hop is allowed, the place it points to is not
    with pytest.raises(FetchError) as error:
        fetch_page(base(server) + "/to-metadata", allowed(server), session)
    assert "private" in str(error.value)


def test_a_redirect_loop_gives_up(server, session):
    with pytest.raises(FetchError) as error:
        fetch_page(base(server) + "/loop", allowed(server), session)
    assert "redirected more than" in str(error.value)


def test_a_page_over_2mb_is_refused(server, session):
    with pytest.raises(FetchError) as error:
        fetch_page(base(server) + "/big", allowed(server), session)
    assert "2 MB" in str(error.value)


def test_a_page_with_no_readable_text_is_refused(server, session):
    with pytest.raises(FetchError) as error:
        fetch_page(base(server) + "/empty", allowed(server), session)
    assert "JavaScript" in str(error.value)


def test_a_missing_page_is_an_error(server, session):
    with pytest.raises(FetchError) as error:
        fetch_page(base(server) + "/nope/", allowed(server), session)
    assert "404" in str(error.value)


def test_the_address_check_would_refuse_this_server_if_it_werent_allow_listed(server, session):
    # what happens after a DNS answer changes between the check and the connect: the
    # pre-check passed, but the socket is on a private address
    response = session.get(base(server) + "/hollowbrook-bakery/", stream=True)
    try:
        assert not is_public_ip(connected_address(response))
    finally:
        response.close()
