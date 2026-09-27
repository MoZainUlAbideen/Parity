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


async def test_findings_carry_wcag_citations(base_url, browser):
    report = await scan_url(f"{base_url}/broken/images.html", viewports=["desktop"], allow_private=True, browser=browser)
    image_alt = next(f for f in report.findings if f.rule_id == "image-alt")
    assert [c.sc for c in image_alt.citations] == ["1.1.1"]
    assert image_alt.citations[0].handle == "Non-text Content"
    assert image_alt.citations[0].understanding_url.endswith("/non-text-content.html")


async def test_agents_settle_contrast_over_images(base_url, browser):
    from parity.scanner import AgentOptions

    report = await scan_url(f"{base_url}/broken/contrast_images.html", allow_private=True, browser=browser, agents=AgentOptions())
    over = [f for f in report.findings if f.rule_id == "contrast-over-image"]
    assert [n.target for f in over for n in f.nodes] == ["#dark-on-dark"]
    assert over[0].viewports == ["desktop", "mobile"]
    assert over[0].citations[0].sc == "1.4.3"
    assert {r.target for r in report.resolved} == {"#light-on-dark"}  # measured as passing
    assert not [f for f in report.findings if f.confidence == Confidence.needs_review]
    assert report.agents == ["contrast-meter", "interaction-agent", "parity-rules"]


async def test_agents_raise_no_alarms_on_fixed_pages(base_url, browser):
    from parity.scanner import AgentOptions

    for page in ["fixed/contrast_images.html", "fixed/images_quality.html", "clean.html"]:
        report = await scan_url(f"{base_url}/{page}", allow_private=True, browser=browser, agents=AgentOptions())
        assert report.findings == [], page


async def test_one_unmeasurable_element_never_breaks_the_scan(base_url, browser, monkeypatch):
    import parity.scanner as scanner_mod
    from parity.scanner import AgentOptions

    async def exploding(page, selector, *a, **kw):
        raise RuntimeError("Page.screenshot: Clipped area is either empty or outside the resulting image")

    monkeypatch.setattr(scanner_mod, "measure_text_over_image", exploding)
    report = await scan_url(f"{base_url}/broken/contrast_images.html", viewports=["desktop"], allow_private=True, browser=browser, agents=AgentOptions())
    review = [n for f in report.findings if f.confidence == Confidence.needs_review for n in f.nodes]
    assert {n.target for n in review} == {"#dark-on-dark", "#light-on-dark"}  # kept for a human
    assert all("Could not measure" in n.evidence for n in review)
    assert any("could not be measured" in note for note in report.notes)


async def test_findings_know_where_they_are_on_the_screenshot(base_url, browser):
    report = await scan_url(f"{base_url}/broken/images.html", allow_private=True, browser=browser)
    hero = next(n for f in report.findings for n in f.nodes if n.target == "#hero")
    assert hero.box and hero.box["width"] > 100 and hero.box["y"] > 0


async def test_hidden_carousel_slides_get_no_pin(base_url, browser):
    # Regression (Mars demo, 2026-09-27): clipped carousel clones got pins at negative y.
    from parity.scanner import _BOXES_JS
    page = await browser.new_page()
    await page.goto(f"{base_url}/special/clipped_carousel.html")
    sel = [f".track li:nth-of-type({i}) img" for i in (1, 2, 3)]
    boxes = await page.evaluate(_BOXES_JS, sel)
    assert boxes[0] is None and boxes[1] is None
    assert boxes[2] and boxes[2]["y"] > 0 and boxes[2]["height"] > 100


async def test_out_of_time_returns_the_rules_report_with_a_note(base_url, browser):
    # Regression (live on Render's free CPU, 2026-09-27): a slow scan hit the time limit and
    # the visitor got an error instead of the rule-engine results that were already done.
    import time as _t
    from parity.scanner import TIME_NOTE, AgentOptions
    stages = []
    opts = AgentOptions(deadline=_t.monotonic() - 1, on_stage=stages.append)
    report = await scan_url(f"{base_url}/broken/contrast_images.html", allow_private=True, browser=browser, agents=opts)
    assert report.findings, "rule findings must survive"
    assert TIME_NOTE in report.notes
    assert not any(f.source.value == "contrast-meter" for f in report.findings)
    assert any("ran out of time" in n for n in report.notes)
    assert stages[0] == "rules" and "mobile" in stages


async def test_stages_are_reported_in_order(base_url, browser):
    from parity.scanner import AgentOptions
    stages = []
    await scan_url(f"{base_url}/broken/contrast_images.html", allow_private=True, browser=browser,
                   agents=AgentOptions(on_stage=stages.append))
    assert stages == ["rules", "keyboard", "images", "contrast", "mobile"]


async def test_vision_calls_run_while_the_contrast_meter_works(base_url, browser, monkeypatch):
    # Measured live on Render's free CPU (2026-09-27): images=50.5s then contrast=36.4s, back
    # to back, and the time budget ran out. The model calls need no browser, so they overlap.
    import time as _t
    import parity.scanner as scanner_mod
    from parity.scanner import AgentOptions
    events = []

    class SlowVision:
        name = "slow"

        def judge_json(self, prompt, image, mime):
            _t.sleep(0.3)
            events.append(("vision_done", _t.monotonic()))
            return {"alt_verdict": "good", "confidence": 1, "suggested_alt": ""}, self.name

    real = scanner_mod._run_contrast_meter

    async def spy(page, findings, viewport, out_of_time=lambda: False):
        events.append(("contrast_start", _t.monotonic()))
        return await real(page, findings, viewport, out_of_time)

    monkeypatch.setattr(scanner_mod, "_run_contrast_meter", spy)
    await scan_url(f"{base_url}/broken/images_quality.html", viewports=["desktop"], allow_private=True,
                   browser=browser, agents=AgentOptions(vision=SlowVision()))
    contrast_start = next(t for e, t in events if e == "contrast_start")
    last_vision = max(t for e, t in events if e == "vision_done")
    assert contrast_start < last_vision, "contrast meter waited for every vision call"
