# Parity

**Parity finds what's locking disabled users out of your website, explains it in plain words, and fixes it, with proof.**

About 1 in 6 people live with a disability, and 95.9% of the top million homepages fail automated WCAG checks (WebAIM Million 2026). Parity opens a page in a real browser, audits it the way a screen-reader user, a keyboard-only user, and a low-vision user would experience it, and reports each problem with the exact WCAG rule it breaks.

Every finding is labeled honestly:

| Label | Meaning |
|---|---|
| `auto-verified` | A deterministic rule engine confirmed it fails |
| `ai-high-confidence` | An AI agent found it (coming in milestones 3-4) |
| `needs-review` | Parity isn't sure; a human should check |

## Status: Milestone 1 (foundation)

- Real-browser crawler (Playwright + Chromium) scanning desktop and mobile viewports
- Full-page screenshots and the browser's accessibility tree for every page
- axe-core 4.13 rule engine, normalized into WCAG success criteria (1.1.1, 1.4.3, ...)
- Findings merged across viewports (one problem, not two)
- SSRF protection: refuses to scan internal addresses like `localhost` or `169.254.169.254`
- Labeled benchmark: 5 broken pages, their fixed twins, and a clean page (19 labeled issues)
- Detects bot-protection challenge pages (e.g. Cloudflare) and reports the scan as blocked instead of auditing the wrong page
- Baseline eval with precision/recall
- 54 tests

### Baseline: rule engine alone

| Metric | Value |
|---|---|
| Precision | 100% |
| Recall on rule-detectable issues | 100% |
| **Recall on all labeled issues** | **68%** |
| False positives on fixed/clean pages | 0 |

The rules miss 6 of 19 issues, all judgment calls: a chart whose alt text is just "image", a placeholder used as the only label, white text over a background photo, two identical "Read more" links, and a clickable `<div>` a keyboard can't reach. Closing that gap is what the AI agents in the next milestones are for.

Caveat: this benchmark is small and hand-built, so 100% on rule-detectable issues is expected. The W3C "Before and After" demo site and real-world pages are added in later milestones to make the numbers harder.

## Quick start

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run playwright install chromium

uv run pytest                              # run tests
uv run parity scan https://www.w3.org/WAI/demos/bad/before/home.html
uv run parity baseline-eval                # score against the labeled pages
```

Reports and screenshots go to `reports/`.

## Project layout

```
src/parity/
  models.py          Finding, ScanReport, confidence labels
  scanner.py         Real-browser crawl + axe per viewport, merged report
  url_safety.py      SSRF protection
  wcag.py            axe tags -> WCAG success criteria + level
  rules/axe_runner.py   Inject axe-core, normalize and merge results
  rules/vendor/      axe-core (MPL-2.0)
  eval/              Ground-truth scoring and fixture server
  cli.py             `parity scan`, `parity baseline-eval`
eval/
  fixtures/          broken/, fixed/, clean.html
  ground_truth.json  Human-labeled issues (axe-detectable vs AI-only)
  results/           Committed eval results, for tracking over time
tests/
```

## Roadmap

1. Foundation: crawler, rule engine, labeled benchmark, baseline eval (done)
2. WCAG knowledge base + RAG with citations
3. Vision agent: alt text quality, contrast over images
4. Interaction agent: keyboard and focus
5. Orchestrator, critic, report + eval harness v1
6. Fixer agent with re-scan verification and GitHub PRs
7. Live product: backend on Render, frontend on Vercel
8. LLMOps: tracing, CI eval gate, customer GitHub Action, scheduled rescans

## License notes

axe-core is vendored under the Mozilla Public License 2.0 (see `src/parity/rules/vendor/axe-core-LICENSE.txt`).
