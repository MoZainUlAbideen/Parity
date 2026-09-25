import socket

import pytest

from parity.url_safety import UnsafeURLError, validate_target_url


def fake_resolver(ip):
    def _resolve(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    return _resolve


PUBLIC = fake_resolver("93.184.216.34")


def test_adds_https_when_scheme_missing():
    assert validate_target_url("example.com", resolver=PUBLIC) == "https://example.com"


def test_public_url_allowed():
    assert validate_target_url("https://example.com/about", resolver=PUBLIC) == "https://example.com/about"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com", "javascript:alert(1)", "data:text/html,<h1>x</h1>"])
def test_non_http_schemes_rejected(url):
    with pytest.raises(UnsafeURLError):
        validate_target_url(url, resolver=PUBLIC)


def test_host_with_port_but_no_scheme_is_accepted():
    assert validate_target_url("example.com:8080", resolver=PUBLIC) == "https://example.com:8080"


def test_invalid_port_is_a_clean_refusal_not_a_crash():
    with pytest.raises(UnsafeURLError, match="port"):
        validate_target_url("https://example.com:99999999x", resolver=PUBLIC)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000",
        "http://localhost.test",  # resolved below to loopback
        "http://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
        "http://10.0.0.5",
        "http://192.168.1.1",
        "http://[::1]/",
    ],
)
def test_internal_addresses_rejected(url):
    with pytest.raises(UnsafeURLError):
        validate_target_url(url, resolver=fake_resolver("127.0.0.1"))


def test_hostname_that_resolves_to_private_ip_rejected():
    # DNS can point an innocent-looking name at an internal address.
    with pytest.raises(UnsafeURLError, match="internal"):
        validate_target_url("https://sneaky.example", resolver=fake_resolver("10.1.2.3"))


def test_embedded_credentials_rejected():
    with pytest.raises(UnsafeURLError):
        validate_target_url("https://user:pass@example.com", resolver=PUBLIC)


def test_allow_private_for_local_testing():
    assert validate_target_url("http://127.0.0.1:5000", allow_private=True) == "http://127.0.0.1:5000"


def test_unresolvable_host():
    def boom(host, port):
        raise socket.gaierror("nope")

    with pytest.raises(UnsafeURLError, match="resolve"):
        validate_target_url("https://does-not-exist.invalid", resolver=boom)
