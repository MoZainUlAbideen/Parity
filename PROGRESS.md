# Parity progress log

## Milestone 1: Foundation
- [x] Project scaffold with uv (package, CLI entry point, pytest config)
- [x] Real-browser crawler: Playwright + Chromium, desktop and mobile viewports
- [x] Page snapshot: full-page screenshot, accessibility tree, title, lang, DOM size
- [x] axe-core 4.13 vendored and injected into the live page
- [x] axe results normalized: WCAG criteria + level, impact, confidence labels
- [x] Findings merged across viewports; violations win over needs-review
- [x] SSRF protection for user-submitted URLs
- [x] Labeled benchmark: 5 broken pages + fixed twins + clean page, 19 labeled issues
- [x] Baseline eval: precision 100%, rule-detectable recall 100%, overall recall 68%
- [x] CLI: `parity scan`, `parity baseline-eval`
- [x] Bugs found and fixed: `javascript:` URL crashed the validator; `[ai]` label swallowed by terminal markup; strict-CSP sites (w3.org) blocked axe injection; Cloudflare bot-check page was audited as if it were the real site
- [x] Bot-protection detection: challenge pages are reported as blocked, never audited
- [x] Clean one-line errors for failed and blocked scans
- [x] 54 tests passing (Windows and Linux)
- [ ] Push to GitHub, CI green
- [ ] Run a live scan on a real public site from your machine

## Milestone 2: WCAG knowledge base + RAG
- [ ] Ingest WCAG 2.2, Understanding and Techniques pages (W3C, openly licensed)
- [ ] Chunk, embed, retrieve, rerank
- [ ] Every finding cites the exact success criterion
- [ ] Retrieval eval
