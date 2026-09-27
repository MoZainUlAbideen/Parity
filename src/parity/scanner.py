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
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Browser, TimeoutError as PWTimeout, async_playwright

from parity.bot_detection import Challenge, detect_bot_challenge
from parity.agents.contrast import measure_text_over_image
from parity.agents.images import audit_images
from parity.agents.interaction import audit_interaction
from parity.gemini import GeminiVision
from parity.kb.cite import cite_findings
from parity.models import (
    Confidence,
    Finding,
    Impact,
    PageSnapshot,
    Resolved,
    Source,
    ScanReport,
    ScanSummary,
    Viewport,
    VIEWPORTS,
)
from parity.rules.axe_runner import axe_version, merge_findings, normalize_axe_results, run_axe
from parity.url_safety import install_request_guard, validate_target_url

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


@dataclass
class AgentOptions:
    """Which agents run on top of the rule engine.

    contrast: pixel-measure text over background images (free, no model)
    images:   placeholder/file-name alt rules (free), plus vision judgment
              when `vision` is given (uses the Gemini API)
    """

    contrast: bool = True
    images: bool = True
    interaction: bool = True
    vision: GeminiVision | None = None
    max_images: int = 15

    @classmethod
    def rules_only(cls) -> "AgentOptions":
        return cls(contrast=False, images=False, interaction=False)

    def names(self) -> list[str]:
        out = []
        if self.contrast:
            out.append(Source.contrast_meter.value)
        if self.interaction:
            out.append(Source.interaction_agent.value)
        if self.images:
            out.append(Source.parity_rules.value)
        if self.images and self.vision:
            out.append(f"{Source.vision_agent.value}:{self.vision.name}")
        return out


@dataclass
class ViewportResult:
    snapshot: PageSnapshot
    findings: list[Finding]
    resolved: list[Resolved] = field(default_factory=list)
    suggestions: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _is_background_contrast_node(finding: Finding, node) -> bool:
    text = node.failure_summary.lower()
    return finding.rule_id == "color-contrast" and ("background image" in text or "gradient" in text)


MAX_CONTRAST_MEASUREMENTS = 120  # per viewport; bounds scan time on huge pages


async def _run_contrast_meter(page, findings: list[Finding], viewport: str) -> tuple[list[Finding], list[Resolved], list[str]]:
    """Settle axe's 'needs review' contrast-over-image nodes by measuring pixels.

    One element that can't be measured never breaks the scan: it stays
    'needs review' with a note saying why.
    """
    new, resolved, notes = [], [], []
    measured = failed = 0
    for f in findings:
        if f.confidence != Confidence.needs_review:
            continue
        keep = []
        for node in f.nodes:
            m = None
            if _is_background_contrast_node(f, node) and measured < MAX_CONTRAST_MEASUREMENTS:
                measured += 1
                try:
                    m = await measure_text_over_image(page, node.target)
                except Exception as exc:  # element moved, detached, animation, browser quirk...
                    failed += 1
                    node = node.model_copy(update={"evidence": f"Could not measure automatically ({str(exc).splitlines()[0][:120]})."})
            if m is None:
                keep.append(node)
            elif m.verdict == "pass":
                resolved.append(Resolved(rule_id=f.rule_id, target=node.target, evidence=m.evidence))
            elif m.verdict == "fail":
                new.append(Finding(
                    rule_id="contrast-over-image",
                    description="Text over a background image does not have enough contrast to read.",
                    help="Text must have sufficient contrast against the image behind it",
                    help_url="https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html",
                    impact=Impact.serious, wcag_criteria=["1.4.3"], wcag_level="AA",
                    source=Source.contrast_meter, confidence=Confidence.auto_verified, viewports=[viewport],
                    nodes=[node.model_copy(update={"evidence": m.evidence,
                                                   "suggestion": "Use a solid or semi-opaque backdrop behind the text, or change the text color."})],
                ))
            else:  # inconclusive: keep for human review, but attach the measurement
                keep.append(node.model_copy(update={"evidence": m.evidence}))
        f.nodes = keep
    if failed:
        notes.append(f"Contrast meter ({viewport}): {failed} element(s) could not be measured and remain for human review.")
    if measured >= MAX_CONTRAST_MEASUREMENTS:
        notes.append(f"Contrast meter ({viewport}): measured the first {MAX_CONTRAST_MEASUREMENTS} items; the rest remain for human review.")
    return [f for f in findings if f.nodes] + new, resolved, notes


_BOXES_JS = """
(selectors) => selectors.map((sel) => {
  let el = null;
  try { el = document.querySelector(sel); } catch (e) { return null; }
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return null;
  // Only where it can actually be seen: clip by every scrolling/clipping ancestor and the page.
  // (Carousel clones clipped by overflow:hidden sat at negative y on the Mars demo.)
  let x1 = r.left, y1 = r.top, x2 = r.right, y2 = r.bottom;
  for (let a = el.parentElement; a && a !== document.documentElement; a = a.parentElement) {
    const cs = getComputedStyle(a);
    if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') {
      const c = a.getBoundingClientRect();
      x1 = Math.max(x1, c.left); y1 = Math.max(y1, c.top); x2 = Math.min(x2, c.right); y2 = Math.min(y2, c.bottom);
    }
  }
  const sx = window.scrollX, sy = window.scrollY;
  const docW = document.documentElement.scrollWidth, docH = document.documentElement.scrollHeight;
  x1 = Math.max(x1 + sx, 0); y1 = Math.max(y1 + sy, 0); x2 = Math.min(x2 + sx, docW); y2 = Math.min(y2 + sy, docH);
  if (x2 - x1 < 2 || y2 - y1 < 2) return null;  // hidden from view: no pin rather than a wrong one
  return {x: x1, y: y1, width: x2 - x1, height: y2 - y1};
})
"""


async def _attach_boxes(page, findings: list[Finding]) -> None:
    """Record each node's position in full-page coordinates (for pins on the screenshot)."""
    nodes = [n for f in findings for n in f.nodes if ">>>" not in n.target and "|" not in n.target]
    if not nodes:
        return
    boxes = await page.evaluate(_BOXES_JS, [n.target for n in nodes])
    for node, box in zip(nodes, boxes):
        if box:
            node.box = {k: round(v, 1) for k, v in box.items()}


async def _scan_viewport(
    browser: Browser, url: str, viewport: Viewport, out_dir: Path | None,
    agents: AgentOptions, run_image_agent: bool, allow_private: bool = False,
) -> ViewportResult:
    context = await browser.new_context(
        viewport={"width": viewport.width, "height": viewport.height},
        is_mobile=viewport.is_mobile,
        has_touch=viewport.is_mobile,
        # Many sites (w3.org included) send a Content Security Policy that blocks
        # scripts they didn't sign. We inject axe as a script, so our private
        # audit browser ignores CSP. This never touches the real website.
        bypass_csp=True,
    )
    if not allow_private:
        # The first URL was checked, but the page can still pull in internal addresses
        # (iframes, images, redirects). Every request the browser makes is checked too.
        await install_request_guard(context)
    try:
        page = await context.new_page()
        await page.goto(url, wait_until="load", timeout=NAV_TIMEOUT_MS)
        if not allow_private:
            validate_target_url(page.url)  # where redirects actually landed
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
        result = ViewportResult(snapshot=snapshot, findings=normalize_axe_results(raw, viewport.name))

        # Agents add value but must never cost the customer the rule-engine report.
        if agents.contrast:
            try:
                result.findings, result.resolved, notes = await _run_contrast_meter(page, result.findings, viewport.name)
                result.notes += notes
            except Exception as exc:
                result.notes.append(f"Contrast meter failed on {viewport.name}: {str(exc).splitlines()[0][:160]}")
        if agents.interaction and run_image_agent:  # keyboard behaviour: once, on the first viewport
            try:
                ia = await audit_interaction(page)
                for f in ia.findings:
                    f.viewports = [viewport.name]
                result.findings += ia.findings
                result.notes += ia.notes
            except Exception as exc:
                result.notes.append(f"Interaction agent failed on {viewport.name}: {str(exc).splitlines()[0][:160]}")
        if agents.images and run_image_agent:
            try:
                audit = await audit_images(page, agents.vision, agents.max_images, allow_private=allow_private)
                for f in audit.findings:
                    f.viewports = [viewport.name]
                result.findings += audit.findings
                result.suggestions = audit.suggestions
                result.notes += audit.errors
            except Exception as exc:
                result.notes.append(f"Image agent failed on {viewport.name}: {str(exc).splitlines()[0][:160]}")
        if run_image_agent:  # first viewport: locate every problem on its full-page screenshot
            try:
                await _attach_boxes(page, result.findings)
            except Exception as exc:
                result.notes.append(f"Could not locate elements for the annotated screenshot: {str(exc).splitlines()[0][:120]}")
        return result
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
    agents: AgentOptions | None = None,
) -> ScanReport:
    """Scan one URL. Pass an already-open `browser` to reuse it across scans.

    `agents=None` runs the rule engine only; pass AgentOptions() for agents.
    """
    agents = agents or AgentOptions.rules_only()
    url = validate_target_url(url, allow_private=allow_private)
    vps = [VIEWPORTS[v] for v in (viewports or ["desktop", "mobile"])]
    start = time.perf_counter()

    async def _run(b: Browser) -> ScanReport:
        snapshots, per_vp, resolved, suggestions, notes = [], [], [], {}, []
        for i, vp in enumerate(vps):
            # Images look the same at every size, so the (paid) image agent runs once.
            r = await _scan_viewport(b, url, vp, out_dir, agents, run_image_agent=(i == 0), allow_private=allow_private)
            snapshots.append(r.snapshot)
            per_vp.append(r.findings)
            resolved += [x for x in r.resolved if (x.rule_id, x.target) not in {(y.rule_id, y.target) for y in resolved}]
            suggestions.update(r.suggestions)
            notes += r.notes
        findings = cite_findings(merge_findings(per_vp))
        # A failure on ANY screen size wins: an element can't be "settled as passing" on
        # desktop while failing on mobile. Regression (2026-09-27, Deque Mars footer).
        failing = {n.target for f in findings if f.rule_id == "contrast-over-image" for n in f.nodes}
        resolved = [x for x in resolved if x.target not in failing]
        # A resolved item must not linger as "needs review" from another viewport.
        done = {(x.rule_id, x.target) for x in resolved}
        for f in findings:
            if f.confidence == Confidence.needs_review:
                f.nodes = [n for n in f.nodes if (f.rule_id, n.target) not in done]
            for n in f.nodes:  # proposed alt text for images axe flagged as missing alt
                if not n.suggestion and n.target in suggestions:
                    n.suggestion = suggestions[n.target]
        findings = [f for f in findings if f.nodes]
        return ScanReport(
            url=url,
            engine=axe_version(),
            duration_seconds=round(time.perf_counter() - start, 2),
            snapshots=snapshots,
            findings=findings,
            summary=summarize(findings),
            resolved=resolved,
            agents=agents.names(),
            notes=notes,
        )

    if browser is not None:
        return await _run(browser)
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        try:
            return await _run(b)
        finally:
            await b.close()
