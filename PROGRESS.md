# Parity progress log

## Milestone 1: Foundation (done)
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
- [x] Live scan of a real site: Deque Mars demo, 13 issues on 99 elements
- [x] Pushed to GitHub

## Milestone 2: WCAG knowledge base + RAG
- [x] Fetch WCAG 2.2 from W3C's GitHub: 87 criteria + 87 Understanding pages
- [x] Parse into 1,092 passages along W3C's sections; nested-markup duplication fixed, no paragraph lost
- [x] Every finding cites its success criterion (exact lookup, rule text, W3C "why it's important")
- [x] Keyword search (BM25 + stemming), exact criterion lookup, A/AA default
- [x] Semantic search (fastembed bge-small) + hybrid RRF, tested with a stand-in model
- [x] `parity explain`, `parity search`, `parity ask` with quote-verified grounding
- [x] Retrieval eval: 54 golden questions; BM25 hit@5 86% overall, lay hit@1 59%, technical hit@3 100%
- [x] Retrieval quality floor in tests + retrieval eval in CI
- [x] Bug found and fixed: W3C labels "What to do" as "Author task" on 1.4.12 and 2.2.6; plain-language brief was lost
- [x] 95 tests passing
- [ ] Run semantic + hybrid eval on your machine and record the numbers
- [ ] Try `parity ask` live with your Groq key
- [ ] Push to GitHub, CI green

## Milestone 3: Vision agent
- [ ] Alt-text quality: is the description accurate and useful?
- [ ] Decorative vs informative images
- [ ] Contrast over background images (resolve axe's needs-review cases)
- [ ] Re-run baseline eval: recall on AI-only issues
