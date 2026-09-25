"""End-to-end tests with a real headless browser.

Skipped automatically if Chromium isn't installed
(install it with:  uv run playwright install chromium).
"""

from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from parity.eval.fixture_server import serve_directory
from parity.models import Confidence
from parity.scanner import ScanBlockedError, scan_url
from parity.url_safety import UnsafeURLError


@pytest.fixture(scope="module")
def base_url():
    with serve_directory() as base:
        yield base


@pytest.fixture
async def browser():
    async with async_playwright() as pw:
        try:
            b = await pw.chromium.launch()
        except Exception as exc:  # browser binary missing
            pytest.skip(f"Chromium not available: {exc}")
        yield b
        await b.close()


def confirmed(report):
    return {(f.rule_id, n.target) for f in report.findings if f.confidence == Confidence.auto_verified for n in f.nodes}


async def test_broken_images_page_flags_missing_alt(base_url, browser, tmp_path):
    report = await scan_url(f"{base_url}/broken/images.html", allow_private=True, browser=browser, out_dir=tmp_path)
    assert ("image-alt", "#hero") in confirmed(report)
    assert ("link-name", "#logo-link") in confirmed(report)
    # screenshots were captured for both viewports
    assert {s.viewport for s in report.snapshots} == {"desktop", "mobile"}
    assert all(s.screenshot_path and Path(s.screenshot_path).exists() for s in report.snapshots)


async def test_fixed_twin_has_no_confirmed_issues(base_url, browser):
    report = await scan_url(f"{base_url}/fixed/images.html", allow_private=True, browser=browser)
    assert confirmed(report) == set()


async def test_clean_page_has_zero_findings(base_url, browser):
    report = await scan_url(f"{base_url}/clean.html", allow_private=True, browser=browser)
    assert report.findings == []
    assert report.summary.total_findings == 0


async def test_snapshot_captures_accessibility_tree_and_metadata(base_url, browser):
    report = await scan_url(f"{base_url}/clean.html", viewports=["desktop"], allow_private=True, browser=browser)
    snap = report.snapshots[0]
    assert snap.title == "Northwind - Contact"
    assert snap.lang == "en"
    assert "heading" in snap.aria_snapshot and "Contact us" in snap.aria_snapshot
    assert snap.dom_size > 10


async def test_local_url_refused_without_allow_flag(base_url):
    with pytest.raises(UnsafeURLError):
        await scan_url(f"{base_url}/clean.html")


async def test_page_with_strict_content_security_policy_is_still_scanned(base_url, browser):
    # Regression: w3.org's CSP blocked axe's inline script and crashed the scan.
    report = await scan_url(f"{base_url}/special/csp_strict.html", viewports=["desktop"], allow_private=True, browser=browser)
    assert ("image-alt", "#no-alt") in confirmed(report)


async def test_bot_challenge_page_is_reported_as_blocked_not_audited(base_url, browser):
    # Regression: w3.org served a Cloudflare challenge and we "audited" it,
    # reporting 1 issue for the wrong page. Now we refuse to report on it.
    with pytest.raises(ScanBlockedError, match="Cloudflare"):
        await scan_url(f"{base_url}/special/bot_challenge.html", viewports=["desktop"], allow_private=True, browser=browser)
