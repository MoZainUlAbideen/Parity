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
- [x] `parity agent-eval` with Gemini on your machine: 80% precision (false alarms on correct alt text)
- [x] Mars scan with vision: meter settled 66 of 86 contrast cases, 11 real failures
- [x] Vision consistency checks + W3C chart/link guidance in the prompt; replay of the real answers: 100% precision, 100% recall
- [x] Bug found on Mars: a wrapping link read neighbouring words as background (false 1.28:1 fail). Now hides all text incl. ::before/::after (16.94:1)
- [x] Bug: same element "passing" on desktop and "failing" on mobile. A failure on any screen wins
- [x] Recorded-answer replay tests (no API calls in CI)

## Milestone 4: Interaction agent (done)
- [x] Keyboard Tab walk; clickable-but-unreachable elements fail 2.1.1
- [x] Ambiguous "Read more" links fail 2.4.4; placeholder-only labels
- [x] Bug caught by tests: malformed/about:blank hrefs crashed the link check
- [x] No-AI recall 75% -> 92%, still 100% precision
- [x] Element positions recorded, so the report pins each problem on the screenshot

## Milestone 5: Live product
- [x] FastAPI backend: scan queue, polling, screenshots, /api/ask; rate limits, queue cap, TTL, SSRF guard, CORS
- [x] Dockerfile (Playwright base + uv) and render.yaml
- [x] Website: home (hear it / see it / try it), plain-words report with pins and filters, how-it-works with honest numbers, bottom-left WCAG assistant
- [x] Reviewed as a visitor on desktop and phone: fixed cramped hero card, nav wrapping on phones, chat button covering content (now shrinks to an icon when you scroll), report gutters, confusing "23 left for review" label
- [x] Parity audited its own site: found 15 identical "What W3C says" links + unscrollable tables; fixed; now a test (all 3 pages pass)
- [x] 197 tests passing
- [x] Mars scan with all agents on your machine: 16 confirmed kinds, 113 places, 65 contrast cases settled
- [x] Bug found in that report: carousel clones clipped by overflow:hidden were photographed in place, so Gemini judged the badge on top of them and gave different alt text for the same image. Now judged from the image's own pixels, repeats judged once (saves quota too)
- [x] Same bug gave hidden slides pins at negative positions: pins now only where the element can be seen
- [x] Security gap found while fixing it: only the typed URL was SSRF-checked. Now every browser request and the final redirect target are checked
- [x] Semantic search model now installed by plain `uv sync`; Windows test warnings fixed (197 -> 205 tests)
- [x] Mars scan + export with the image fix: "It sees" now matches each photo, one answer per repeated image, no quota cut-off
- [x] Live `agent-eval` with Gemini: precision 100%, recall 100% (24/24), 0 false alarms, 1 left for review
- [x] Render + Vercel live; chat answers on the live site
- [x] Bug found live: `ALLOWED_ORIGINS` with a trailing slash blocked every browser request. Origins are now normalised (+2 tests)
- [x] Bug found live: on Render's free CPU a full scan passed the 150 s limit and the visitor got only an error. Now optional checks stop at 55% of a 240 s limit and the report says what was skipped; rules results are never lost (+2 tests)
- [x] Progress page shows the scanner's real stage instead of a timed guess; stage timings in the server logs
- [ ] Live scan of Mars finishes on Render
- [ ] Add the retrieval-eval step to CI by hand; push; CI green
