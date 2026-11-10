import socket

import pytest

from backend.app.fetcher import FetchError, check_url, is_public_ip


def resolver(*addresses):
    def resolve(host, port, type=None):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
                for address in addresses]
    return resolve


def no_dns(host, port, type=None):
    raise AssertionError("DNS shouldn't be asked about " + host)


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.1.1", "169.254.169.254", "0.0.0.0",
    "100.64.0.1", "::1", "fe80::1", "fd00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1",
    "224.0.0.1",
])
def test_private_and_internal_addresses_are_not_public(address):
    assert not is_public_ip(address)


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_are_public(address):
    assert is_public_ip(address)


@pytest.mark.parametrize("url", [
    "ftp://example.com/shop", "file:///etc/passwd", "gopher://example.com", "javascript:1",
    "example.com/shop", "", "http://", "https://user:secret@example.com/",
])
def test_only_plain_http_and_https(url):
    with pytest.raises(FetchError):
        check_url(url, resolve=no_dns)


def test_host_that_resolves_to_a_private_address_is_blocked():
    with pytest.raises(FetchError) as error:
        check_url("https://shop.example/menu", resolve=resolver("10.1.2.3"))
    assert "private" in str(error.value)


def test_cloud_metadata_address_is_blocked():
    with pytest.raises(FetchError):
        check_url("http://169.254.169.254/latest/meta-data/",
                  resolve=resolver("169.254.169.254"))


def test_one_private_answer_among_public_ones_blocks_the_host():
    with pytest.raises(FetchError):
        check_url("https://shop.example/", resolve=resolver("93.184.216.34", "127.0.0.1"))


def test_localhost_is_blocked_by_default():
    with pytest.raises(FetchError):
        check_url("http://localhost:5174/store/", resolve=resolver("127.0.0.1"))


def test_public_host_is_allowed():
    parts = check_url("https://shop.example/menu", resolve=resolver("93.184.216.34"))
    assert parts.hostname == "shop.example"


def test_allow_list_is_exact_host_and_port():
    allowed = {"localhost:5174"}
    check_url("http://localhost:5174/hollowbrook-bakery/", allowed, resolve=no_dns)
    # same host, another port: not on the list
    with pytest.raises(FetchError):
        check_url("http://localhost:8000/", allowed, resolve=resolver("127.0.0.1"))


def test_unknown_host_is_a_fetch_error():
    def failing(host, port, type=None):
        raise socket.gaierror("no such host")

    with pytest.raises(FetchError):
        check_url("https://nope.invalid/", resolve=failing)
