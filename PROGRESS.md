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
- [x] 107 tests passing
- [x] Semantic eval on your machine: hit@5 92% vs keyword 86%; lay-phrasing hit@5 88% vs 78%; now the default
- [x] `parity ask` live with gpt-oss-120b: correct, quotes verified
- [x] Bug found in live use: answers cited examples, not the rule; rule text now always offered
- [x] Bug found by the eval: hybrid v1 worse than both parts (passage-level fusion lost cross-method agreement, e.g. T12); now fuses criteria
- [x] Query-embedding cache (repeat questions skip the model; eval runs replayable)
- [x] Groq model discovery: `parity models`, clear error when a model is retired
- [x] Hybrid v2 measured: hit@1 73%, hit@5 92%, MRR 0.81, lay hit@1 62%; now the default
- [x] Pushed to GitHub

## Milestone 3: Vision + measurement agents
- [x] Benchmark v2: image-quality and text-over-image pages, fixed twins, correct "negative" cases; 24 labeled issues (11 AI-only)
- [x] Contrast meter: measures text over background images from pixels; settles axe's needs-review cases (pass or fail, with the ratio)
- [x] Alt-text rules: placeholder and file-name alt text (W3C F30), no model needed
- [x] Gemini vision client: retries + backoff, model fallbacks, disk cache, rate spacing, model discovery (`parity models --provider gemini`)
- [x] Vision agent: alt-text quality, hidden informative images, suggested alt text for every image
- [x] Evidence and suggested fix on every agent finding; "settled as passing" list in reports
- [x] `parity agent-eval`: rules only 54% recall / AI-only 0% / 5 left for review -> agents without AI 75% / 45% / 0, still 100% precision and no false alarms
- [x] Agent eval gate in tests (precision, AI-only recall floor, needs-review reduction)
- [x] Pillow deprecation caught (getdata removed in Pillow 14) and handled with a fallback
- [x] Bug found on a real site (Deque Mars, mobile): pages without a viewport meta tag are zoomed out on phones and the meter's crop landed outside the screenshot, crashing the scan. Now measures via element screenshots with proportional crops; failures stay with a human and never break the scan
- [x] Bug caught by tests during that fix: re-reading positions while text was hidden also read text-shadow as "none"
- [x] 163 tests passing
- [ ] Run `parity agent-eval` with Gemini on your machine
- [ ] Scan a real site with the vision agent (Deque Mars: 86 needs-review contrast items)
- [ ] Push to GitHub, CI green
