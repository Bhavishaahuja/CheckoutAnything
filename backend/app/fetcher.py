# Fetch a store page and turn it into plain text. No headless browser, static HTML only.
#
# The URL comes from whoever is using the app, so this is the SSRF surface. Guards:
#   - http and https only, no credentials in the URL
#   - every address the host resolves to has to be a public one (before connecting)
#   - the address we actually ended up connected to is checked again before reading the body,
#     which is what stops a DNS answer that changes between the check and the connect
#   - redirects are followed by hand (max 3) and each hop goes through the same checks
#   - 10 second timeout, 2 MB cap on the body

import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests

FETCH_TIMEOUT_SECONDS = 10
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
# what we're willing to send to Claude. a page with more text than this fails out loud,
# it never gets quietly cut short
MAX_TEXT_CHARS = 150_000

USER_AGENT = "CheckoutAnything/0.1 (store page reader)"


class FetchError(Exception):
    pass


@dataclass
class FetchedPage:
    url: str
    final_url: str
    title: str
    text: str


# ---- SSRF guard ----


def is_public_ip(address):
    ip = ipaddress.ip_address(address)
    # an IPv4 address wrapped in IPv6 (::ffff:10.0.0.1) is judged as the IPv4 one
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def host_key(parts):
    # "localhost:5174", the shape FETCH_ALLOW_HOSTS uses
    port = parts.port
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    return (parts.hostname or "").lower() + ":" + str(port)


def check_url(url, allow_hosts=None, resolve=socket.getaddrinfo):
    # raises FetchError unless this URL is safe to request. returns the parsed parts
    allow_hosts = allow_hosts or set()
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise FetchError("That doesn't look like a URL") from error

    if parts.scheme not in ("http", "https"):
        raise FetchError("Only http and https URLs can be connected")
    if not parts.hostname:
        raise FetchError("That URL has no host")
    if parts.username or parts.password:
        raise FetchError("URLs with a username or password in them aren't allowed")

    if host_key(parts) in allow_hosts:
        return parts

    if port is None:
        port = 443 if parts.scheme == "https" else 80
    try:
        answers = resolve(parts.hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as error:
        raise FetchError("Couldn't find the host " + parts.hostname) from error

    if not answers:
        raise FetchError("Couldn't find the host " + parts.hostname)
    for answer in answers:
        address = answer[4][0]
        if not is_public_ip(address):
            raise FetchError("That host points at a private or internal address")
    return parts


def connected_address(response):
    # the address the socket is really connected to. urllib3 keeps the connection on the raw
    # response while the body is still unread (we always ask for stream=True)
    connection = getattr(response.raw, "connection", None) or getattr(
        response.raw, "_connection", None
    )
    sock = getattr(connection, "sock", None)
    if sock is None:
        return None
    try:
        return sock.getpeername()[0]
    except OSError:
        return None


# ---- fetching ----


def fetch_page(url, allow_hosts=None, session=None):
    session = session or requests.Session()
    allow_hosts = allow_hosts or set()
    current_url = url.strip()

    for _hop in range(MAX_REDIRECTS + 1):
        parts = check_url(current_url, allow_hosts)
        try:
            response = session.get(
                current_url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"},
                timeout=FETCH_TIMEOUT_SECONDS,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as error:
            raise FetchError("Couldn't reach the page: " + type(error).__name__) from error

        try:
            if host_key(parts) not in allow_hosts:
                address = connected_address(response)
                # no address means we can't prove where the answer came from, so don't read it
                if address is None or not is_public_ip(address):
                    raise FetchError("That host points at a private or internal address")

            if response.is_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise FetchError("The page redirected without saying where to")
                current_url = urljoin(current_url, location)
                continue

            if response.status_code != 200:
                raise FetchError("The page answered " + str(response.status_code))

            html = read_capped(response)
        finally:
            response.close()

        title, text = html_to_text(html)
        if not text.strip():
            raise FetchError(
                "The page has no readable text. It may be drawn by JavaScript, "
                "which isn't supported"
            )
        if len(text) > MAX_TEXT_CHARS:
            raise FetchError(
                "The page has " + str(len(text)) + " characters of text, the limit is "
                + str(MAX_TEXT_CHARS)
            )
        return FetchedPage(url=url, final_url=current_url, title=title, text=text)

    raise FetchError("The page redirected more than " + str(MAX_REDIRECTS) + " times")


def read_capped(response):
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > MAX_PAGE_BYTES:
        raise FetchError("The page is bigger than 2 MB")

    chunks = []
    size = 0
    try:
        for chunk in response.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > MAX_PAGE_BYTES:
                raise FetchError("The page is bigger than 2 MB")
            chunks.append(chunk)
    except requests.RequestException as error:
        raise FetchError("The page stopped loading part way: " + type(error).__name__) from error

    body = b"".join(chunks)
    encoding = response.encoding or "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


# ---- HTML to text ----

# nothing inside these is something a shopper reads
SKIPPED_TAGS = {"script", "style", "noscript", "svg", "template", "head", "iframe"}
# these start a new line, so a price stays on the line of the thing it belongs to
BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "main", "aside", "nav",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table", "tr", "br", "hr",
    "blockquote", "pre", "figure", "figcaption", "dl", "dt", "dd", "form", "details", "summary",
}
# crossed-out text. wrapped in ~~ so an old price can be told apart from the current one
STRUCK_TAGS = {"s", "del", "strike"}
CELL_TAGS = {"td", "th"}


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pieces = []
        self.skip_depth = 0
        self.in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag in SKIPPED_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in BLOCK_TAGS:
            self.pieces.append("\n")
        elif tag in CELL_TAGS:
            self.pieces.append(" | ")
        elif tag in STRUCK_TAGS:
            self.pieces.append(" ~~")
        elif tag == "img":
            # alt text is part of what the page says, a price that's only pixels isn't
            for name, value in attrs:
                if name == "alt" and value:
                    self.pieces.append(" [image: " + value + "] ")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in SKIPPED_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in BLOCK_TAGS:
            self.pieces.append("\n")
        elif tag in STRUCK_TAGS:
            self.pieces.append("~~ ")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.skip_depth:
            return
        # a line break in the HTML source is just a space. only block tags start a new line,
        # so a table row's name and price end up on the same line
        self.pieces.append(re.sub(r"\s+", " ", data))


def html_to_text(html):
    parser = TextExtractor()
    parser.feed(html)
    parser.close()

    raw = "".join(parser.pieces).replace("\xa0", " ")
    lines = []
    for line in raw.split("\n"):
        line = re.sub(r"[ \t\r\f\v]+", " ", line).strip()
        if line:
            lines.append(line)
    text = "\n".join(lines)
    # "~~ $8 ~~" -> "~~$8~~"
    text = re.sub(r"~~\s*([^~\n]*?)\s*~~", r"~~\1~~", text)
    title = " ".join(parser.title.split())
    return title, text
