"""Guard against scanning things we must never scan.

Parity opens any URL a stranger types into a real browser on our server.
Without checks, someone could ask it to load http://169.254.169.254/ (cloud
metadata with secrets) or http://localhost:8000/admin. That attack is called
SSRF (server-side request forgery). We block private and internal addresses
unless the caller explicitly allows them (for local testing).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    pass


ALLOWED_SCHEMES = {"http", "https"}


def _is_internal(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_target_url(
    url: str,
    *,
    allow_private: bool = False,
    resolver=socket.getaddrinfo,
) -> str:
    """Return a normalized URL, or raise UnsafeURLError.

    `resolver` is injectable so tests don't need real DNS.
    """
    url = url.strip()
    if "://" not in url:
        # "javascript:alert(1)" or "data:..." are schemes, not host names.
        # "example.com:8080" and "localhost:3000" are host:port.
        head, sep, rest = url.partition(":")
        is_host_port = sep and (rest.split("/")[0].isdigit() or "." in head)
        if sep and not is_host_port:
            raise UnsafeURLError(f"Only http and https URLs can be scanned, got '{head}'.")
        url = "https://" + url  # people type "example.com"
    parsed = urlparse(url)

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"Only http and https URLs can be scanned, got '{parsed.scheme}'.")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no host name.")
    if parsed.username or parsed.password:
        raise UnsafeURLError("URLs with embedded credentials are not allowed.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeURLError("URL has an invalid port.") from exc

    if allow_private:
        return url

    host = parsed.hostname
    try:
        # A literal IP needs no DNS lookup.
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = resolver(host, port or 443)
        except socket.gaierror as exc:
            raise UnsafeURLError(f"Could not resolve host '{host}'.") from exc
        addresses = [ipaddress.ip_address(info[4][0]) for info in infos]

    for ip in addresses:
        if _is_internal(ip):
            raise UnsafeURLError(f"'{host}' points to an internal address ({ip}); refusing to scan.")
    return url


def is_safe_request_url(url: str, *, resolver=socket.getaddrinfo, _cache: dict | None = None) -> bool:
    """For every request the page makes (images, iframes, scripts), not just the page itself.

    A public page can embed <iframe src="http://169.254.169.254/..."> or an internal admin
    page, and the screenshot we hand back would show it. Non-network schemes (data:, blob:)
    never leave the browser, so they're fine. Results are cached per host.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return parsed.scheme in ("data", "blob", "about")
    key = (parsed.hostname, parsed.port)
    if _cache is not None and key in _cache:
        return _cache[key]
    try:
        validate_target_url(url, resolver=resolver)
        ok = True
    except UnsafeURLError:
        ok = False
    if _cache is not None:
        _cache[key] = ok
    return ok


async def install_request_guard(context, *, resolver=socket.getaddrinfo) -> None:
    """Abort any browser request to an internal address (SSRF through page content)."""
    import asyncio

    cache: dict = {}

    async def guard(route):
        url = route.request.url
        ok = await asyncio.to_thread(is_safe_request_url, url, resolver=resolver, _cache=cache)
        if ok:
            await route.continue_()
        else:
            await route.abort("blockedbyclient")

    await context.route("**/*", guard)
