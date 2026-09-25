"""Baseline eval: how well does the rule engine alone do on the labeled pages?

This number is the bar every later milestone (vision agent, interaction
agent, critic) has to beat. Run it with:  uv run parity baseline-eval
"""

from __future__ import annotations

from playwright.async_api import async_playwright

from parity.eval.fixture_server import FIXTURES_DIR, REPO_ROOT, serve_directory
from parity.eval.metrics import EvalResult, GroundTruth, score
from parity.rules.axe_runner import axe_version
from parity.scanner import scan_url

GROUND_TRUTH_PATH = REPO_ROOT / "eval" / "ground_truth.json"


async def run_baseline() -> EvalResult:
    truth = GroundTruth.load(GROUND_TRUTH_PATH)
    findings_by_page = {}
    with serve_directory(FIXTURES_DIR) as base:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                for lp in truth.pages:
                    report = await scan_url(f"{base}/{lp.page}", allow_private=True, browser=browser)
                    findings_by_page[lp.page] = report.findings
            finally:
                await browser.close()
    return score(truth, findings_by_page, engine=axe_version())
