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


# ---------------------------------------------------------------- requests made by the page
from parity.url_safety import is_safe_request_url  # noqa: E402


def _public(host, port):
    return [(None, None, None, None, ("93.184.216.34", port))]


def test_page_requests_to_internal_addresses_are_refused():
    assert not is_safe_request_url("http://169.254.169.254/latest/meta-data/", resolver=_public)
    assert not is_safe_request_url("http://127.0.0.1:8000/admin", resolver=_public)
    assert not is_safe_request_url("http://10.0.0.5/", resolver=_public)


def test_page_requests_to_public_hosts_and_inline_data_are_allowed():
    assert is_safe_request_url("https://cdn.example.com/a.png", resolver=_public)
    assert is_safe_request_url("data:image/png;base64,AAAA")
    assert not is_safe_request_url("file:///etc/passwd")


def test_host_names_that_resolve_inside_are_refused_and_cached():
    calls = []

    def internal(host, port):
        calls.append(host)
        return [(None, None, None, None, ("192.168.1.1", port))]

    cache: dict = {}
    assert not is_safe_request_url("https://intranet.example/a.png", resolver=internal, _cache=cache)
    assert not is_safe_request_url("https://intranet.example/b.png", resolver=internal, _cache=cache)
    assert calls == ["intranet.example"]


async def test_browser_blocks_embedded_internal_requests():
    from playwright.async_api import async_playwright

    from parity.url_safety import install_request_guard

    async with async_playwright() as pw:
        try:
            b = await pw.chromium.launch()
        except Exception as exc:  # pragma: no cover
            import pytest
            pytest.skip(f"Chromium not available: {exc}")
        context = await b.new_context()
        await install_request_guard(context, resolver=_public)
        page = await context.new_page()
        failed = []
        page.on("requestfailed", lambda r: failed.append(r.url))
        await page.set_content('<img src="http://169.254.169.254/latest/meta-data/x.png">'
                               '<iframe src="http://127.0.0.1:9/admin"></iframe>')
        await page.wait_for_timeout(300)
        await b.close()
    assert any("169.254.169.254" in u for u in failed)
    assert any("127.0.0.1:9" in u for u in failed)
