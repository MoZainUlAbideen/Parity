"""Parity's own website must pass Parity's own audit (rules + contrast meter + keyboard agent).

The first run of this check caught real problems on our report page: 15 "What W3C says" links
that sounded identical to a screen reader, and scrollable tables a keyboard couldn't reach.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from parity.eval.fixture_server import REPO_ROOT, serve_directory
from parity.scanner import AgentOptions, scan_url

WEB = REPO_ROOT / "web"
PAGES = ["index.html", "report.html?example=mars", "how.html"]


@pytest.fixture(scope="module")
def site_url():
    with serve_directory(WEB) as url:
        yield url


@pytest.mark.skipif(not (WEB / "index.html").exists(), reason="website not present")
@pytest.mark.parametrize("page", PAGES)
async def test_our_own_site_passes_our_own_audit(site_url, page, tmp_path: Path):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            report = await scan_url(f"{site_url}/{page}", out_dir=tmp_path, allow_private=True,
                                    browser=browser, agents=AgentOptions(images=False))
        finally:
            await browser.close()
    problems = [(f.rule_id, f.nodes[0].target) for f in report.findings]
    assert problems == [], f"{page} fails its own audit: {problems}"
