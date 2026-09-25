"""Open a page in a real browser, capture it, and run the rule engine.

For each viewport (desktop, mobile) we:
  1. load the page in headless Chromium
  2. capture a full-page screenshot and the accessibility tree
  3. run axe-core against the rendered DOM
Then findings from all viewports are merged into one report.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from playwright.async_api import Browser, TimeoutError as PWTimeout, async_playwright

from parity.bot_detection import Challenge, detect_bot_challenge
from parity.models import (
    Confidence,
    Finding,
    PageSnapshot,
    ScanReport,
    ScanSummary,
    Viewport,
    VIEWPORTS,
)
from parity.rules.axe_runner import axe_version, merge_findings, normalize_axe_results, run_axe
from parity.url_safety import validate_target_url

NAV_TIMEOUT_MS = 30_000
SETTLE_TIMEOUT_MS = 5_000
CHALLENGE_WAIT_SECONDS = 6  # some checks clear on their own; we only wait, never interact


class ScanBlockedError(RuntimeError):
    """The site's bot protection answered instead of the real page."""


async def _find_challenge(page) -> Challenge | None:
    info = await page.evaluate(
        """() => ({
            title: document.title,
            text: (document.body && document.body.innerText || '').slice(0, 5000),
            scripts: Array.from(document.scripts).map(s => s.src).filter(Boolean),
        })"""
    )
    return detect_bot_challenge(info["title"], info["text"], info["scripts"])


async def _ensure_not_challenged(page, url: str) -> None:
    challenge = await _find_challenge(page)
    if challenge is None:
        return
    await page.wait_for_timeout(CHALLENGE_WAIT_SECONDS * 1000)
    challenge = await _find_challenge(page)
    if challenge is not None:
        raise ScanBlockedError(
            f"{challenge.vendor} bot protection served a challenge page instead of {url} "
            f"(detected by {challenge.signal}). Parity does not bypass bot protection, so no "
            f"report was produced. The site owner can allowlist the scanner, or you can scan "
            f"a copy of the page."
        )


def _slug(url: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", url.split("://", 1)[-1]).strip("-")[:80] or "page"


async def _scan_viewport(
    browser: Browser, url: str, viewport: Viewport, out_dir: Path | None
) -> tuple[PageSnapshot, list[Finding]]:
    context = await browser.new_context(
        viewport={"width": viewport.width, "height": viewport.height},
        is_mobile=viewport.is_mobile,
        has_touch=viewport.is_mobile,
        # Many sites (w3.org included) send a Content Security Policy that blocks
        # scripts they didn't sign. We inject axe as a script, so our private
        # audit browser ignores CSP. This never touches the real website.
        bypass_csp=True,
    )
    try:
        page = await context.new_page()
        await page.goto(url, wait_until="load", timeout=NAV_TIMEOUT_MS)
        try:
            # Let late JavaScript finish; many sites never go fully idle, so cap it.
            await page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
        except PWTimeout:
            pass

        # Never audit a bot-check page and pretend it's the customer's site.
        await _ensure_not_challenged(page, url)

        screenshot_path = None
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            shot = out_dir / f"{_slug(url)}-{viewport.name}.png"
            await page.screenshot(path=str(shot), full_page=True)
            screenshot_path = str(shot)

        snapshot = PageSnapshot(
            viewport=viewport.name,
            requested_url=url,
            final_url=page.url,
            title=await page.title(),
            lang=await page.evaluate("document.documentElement.getAttribute('lang')"),
            screenshot_path=screenshot_path,
            aria_snapshot=await page.locator("body").aria_snapshot(),
            dom_size=await page.evaluate("document.getElementsByTagName('*').length"),
        )
        raw = await run_axe(page)
        return snapshot, normalize_axe_results(raw, viewport.name)
    finally:
        await context.close()


def summarize(findings: list[Finding]) -> ScanSummary:
    by_impact: dict[str, int] = {}
    by_conf: dict[str, int] = {}
    elements = 0
    for f in findings:
        by_impact[f.impact.value] = by_impact.get(f.impact.value, 0) + 1
        by_conf[f.confidence.value] = by_conf.get(f.confidence.value, 0) + 1
        if f.confidence == Confidence.auto_verified:
            elements += len(f.nodes)
    return ScanSummary(
        total_findings=len(findings),
        by_impact=by_impact,
        by_confidence=by_conf,
        affected_elements=elements,
    )


async def scan_url(
    url: str,
    viewports: list[str] | None = None,
    out_dir: Path | None = None,
    allow_private: bool = False,
    browser: Browser | None = None,
) -> ScanReport:
    """Scan one URL. Pass an already-open `browser` to reuse it across scans."""
    url = validate_target_url(url, allow_private=allow_private)
    vps = [VIEWPORTS[v] for v in (viewports or ["desktop", "mobile"])]
    start = time.perf_counter()

    async def _run(b: Browser) -> ScanReport:
        snapshots, per_vp = [], []
        for vp in vps:
            snap, findings = await _scan_viewport(b, url, vp, out_dir)
            snapshots.append(snap)
            per_vp.append(findings)
        findings = merge_findings(per_vp)
        return ScanReport(
            url=url,
            engine=axe_version(),
            duration_seconds=round(time.perf_counter() - start, 2),
            snapshots=snapshots,
            findings=findings,
            summary=summarize(findings),
        )

    if browser is not None:
        return await _run(browser)
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        try:
            return await _run(b)
        finally:
            await b.close()
