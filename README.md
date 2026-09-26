# Parity

**Parity finds what's locking disabled users out of your website, explains it in plain words, and fixes it, with proof.**

About 1 in 6 people live with a disability, and 95.9% of the top million homepages fail automated WCAG checks (WebAIM Million 2026). Parity opens a page in a real browser, audits it the way a screen-reader user, a keyboard-only user, and a low-vision user would experience it, and reports each problem with the exact WCAG rule it breaks.

Every finding is labeled honestly:

| Label | Meaning |
|---|---|
| `auto-verified` | A deterministic rule or measurement confirmed it fails |
| `ai-high-confidence` | An AI agent found it and is at least 80% sure |
| `needs-review` | Parity isn't sure; a human should check |

## Status: Milestone 3 (vision + measurement agents)

### Milestone 1: foundation
- Real-browser crawler (Playwright + Chromium) scanning desktop and mobile viewports
- Full-page screenshots and the browser's accessibility tree for every page
- axe-core 4.13 rule engine, normalized into WCAG success criteria (1.1.1, 1.4.3, ...)
- Findings merged across viewports (one problem, not two)
- SSRF protection: refuses to scan internal addresses like `localhost` or `169.254.169.254`
- Detects bot-protection challenge pages (e.g. Cloudflare) and reports the scan as blocked instead of auditing the wrong page
- Labeled benchmark: 5 broken pages, their fixed twins, and a clean page (19 labeled issues)

### Milestone 2: WCAG knowledge base
- **Built from W3C's own sources**: all 87 WCAG 2.2 success criteria and their Understanding documents, pulled from W3C's GitHub repositories, chunked along W3C's own sections (rule, in brief, intent, benefits, examples, techniques and failures) into 1,092 passages
- **Every finding cites its rule**: a scan finding carries the success criterion, level, rule text and W3C's plain-language "why it's important". Citing is an exact lookup, never a search, so it can't be hallucinated
- **Search in plain words**: `parity search "people keep tapping the wrong link on phones"` finds 2.5.8 Target Size. BM25 keyword search is always available; semantic search (bge-small, CPU) and hybrid fusion (RRF over criteria, the default when the model is installed) are optional
- **Grounded answers**: `parity ask` answers from retrieved WCAG passages only. The model must copy exact quotes, code verifies each quote word for word against the passage, and unverified citations are dropped. If nothing survives, Parity says it couldn't verify an answer instead of guessing
- **Targets WCAG A/AA by default**, the level laws point to, so answers don't cite stricter AAA rules nobody is required to meet
- 95 tests, including a retrieval quality floor that fails CI if search gets worse

### Milestone 3: agents for what rules can't judge
- **Contrast meter (no AI).** axe can't compute contrast for text over a background image, so it marks it "needs review". Parity renders the background without the text, screenshots exactly the text area and measures the text color against every pixel, judging the hardest-to-read 5% against WCAG's 4.5:1 (3:1 for large text). Passing text is settled as passing, failing text becomes a finding with the measured ratio. Text with shadows or outlines stays with a human, with the number attached
- **Alt-text rules (no AI).** Alt text that is a placeholder ("banner", "image") or a file name ("chart_final_v2.png") is always a failure (W3C failure F30), and axe doesn't check for it
- **Vision agent (Gemini).** Looks at each image with its context (link, caption, heading, nearby text) and judges whether the alt text conveys the same information, whether an image marked decorative actually carries information, and proposes alt text for every image, including the ones axe flags as missing alt. Built for a crowded free tier: retries with backoff, model fallbacks, a disk cache (the same image is never paid for twice), and a per-page image cap
- **Robust on real sites.** Measured through element screenshots, so zoomed-out mobile layouts work (found on the Deque Mars demo, which has no viewport meta tag); an element that can't be measured stays with a human and never breaks the scan
- **Evidence on every finding.** Each agent finding carries how it was decided (a measured ratio, the rule, or the model's reason and confidence) and a suggested fix

| Configuration | Precision | Recall (all 24) | Recall (AI-only 11) | False alarms on fixed pages | Left for human review |
|---|---|---|---|---|---|
| Rules only (axe) | 100% | 54% | 0% | 0 | 5 |
| Rules + agents, no AI | 100% | 75% | 45% | 0 | 0 |
| Rules + agents + Gemini vision | | *run locally* | | | |

The benchmark now includes deliberately correct cases (a good chart description, a correctly hidden decorative divider, white text that really is readable over a dark photo), so false alarms are measured, not assumed.

### Baseline: rule engine alone (milestone 1)

| Metric | Value |
|---|---|
| Precision | 100% |
| Recall on rule-detectable issues | 100% |
| **Recall on all labeled issues** | **68%** (54% on the larger milestone-3 benchmark) |
| False positives on fixed/clean pages | 0 |

The rules miss 6 of 19 issues, all judgment calls: a chart whose alt text is just "image", a placeholder used as the only label, white text over a background photo, two identical "Read more" links, and a clickable `<div>` a keyboard can't reach. Closing that gap is what the AI agents in the next milestones are for.

### Retrieval: does search find the right WCAG rule? (milestone 2)

54 golden questions, written in the asker's own words (not W3C's) so keyword overlap can't inflate scores.

| Method | Phrasing | Hit@1 | Hit@3 | Hit@5 | MRR |
|---|---|---|---|---|---|
| Keyword (BM25) | all 51 | 71% | 84% | 86% | 0.78 |
| | lay (32) | 59% | 75% | 78% | 0.67 |
| | technical (19) | 89% | 100% | 100% | 0.95 |
| **Semantic (bge-small)** | all 51 | 71% | 86% | **92%** | **0.80** |
| | lay (32) | 56% | 78% | **88%** | 0.69 |
| | technical (19) | **95%** | 100% | 100% | **0.97** |
| Hybrid v1 (passage-level RRF) | all 51 | 65% | 80% | 86% | 0.75 |
| **Hybrid v2 (criterion-level RRF)** | all 51 | **73%** | **86%** | **92%** | **0.81** |
| | lay (32) | **62%** | 78% | 88% | **0.73** |
| | technical (19) | 89% | 100% | 100% | 0.95 |

Semantic search closes much of the gap on everyday phrasing ("the site only works when I hold my tablet upright" goes from not found to 1.3.4 Orientation at #1).

**Hybrid v1 was worse than both of its parts, and the eval caught it.** It fused rankings of individual passages. A WCAG criterion has many passages, so when keyword and semantic search agreed on a criterion through *different* paragraphs, the agreement was never counted: for "aria-live region for announcing search result counts", both methods ranked 4.1.3 Status Messages first, yet hybrid put 1.3.1 first. Hybrid v2 fuses criterion rankings instead (regression test included) and went from worst to best: it ties semantic search on hit@5 and leads on hit@1, MRR and everyday phrasing, so it is the default when the model is installed. The margins are one or two questions out of 51, so treat them as "at least as good", not "clearly better".

Caveat: both benchmarks are small and hand-built. Treat the numbers as a regression baseline, not a claim about real-world accuracy.

## Quick start

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run playwright install chromium
uv run pytest

# Audit a page
uv run parity scan https://dequeuniversity.com/demo/mars/

# WCAG knowledge
uv run parity explain 2.5.8
uv run parity search "people keep tapping the wrong link on phones"

# Semantic + hybrid search (optional, downloads a ~130 MB model once)
uv sync --extra dense
uv run parity retrieval-eval

# Grounded answers (needs GROQ_API_KEY in a .env file)
uv run parity ask "How big do buttons need to be on mobile?"

# Vision agent (needs GEMINI_API_KEY in .env); scan uses it automatically
uv run parity models --provider gemini
uv run parity agent-eval

# Evals
uv run parity baseline-eval
uv run parity retrieval-eval
```

Reports and screenshots go to `reports/`.

### `.env` settings

```
GROQ_API_KEY=...                            # parity ask
GEMINI_API_KEY=...                          # vision agent
PARITY_LLM_MODEL=openai/gpt-oss-120b        # optional
PARITY_VISION_MODELS=gemini-3.1-flash-lite  # optional; comma-separated fallbacks
PARITY_VISION_MIN_INTERVAL=2                # optional; seconds between vision calls
```

## Project layout

```
src/parity/
  models.py            Finding, Citation, ScanReport, confidence labels
  scanner.py           Real-browser crawl + axe + agents per viewport, cited report
  agents/contrast.py   Pixel-measured contrast of text over images
  agents/images.py     Alt-text rules + vision judgment + suggested alt text
  gemini.py            Gemini vision client (retries, fallbacks, cache)
  bot_detection.py     Recognize bot-protection challenge pages
  url_safety.py        SSRF protection
  wcag.py              axe tags -> WCAG success criteria + level
  rules/               axe-core runner (axe vendored, MPL-2.0)
  kb/
    sources.py         Download WCAG 2.2 from W3C's GitHub
    build.py           Parse into criteria + section chunks
    store.py           Load the shipped knowledge base
    bm25.py, text.py   Keyword search with stemming
    dense.py           Semantic search (fastembed, optional)
    retriever.py       Exact lookup + BM25 / dense / hybrid (RRF)
    cite.py            Attach citations to findings
    data/              Built knowledge base (criteria.json, chunks.jsonl)
  ask.py               Grounded answers with verified quotes
  llm.py               Groq client
  eval/                Baseline and retrieval evals, fixture server
  cli.py               All commands
data/wcag/raw/         W3C source files (see data/wcag/NOTICE.md)
eval/
  fixtures/            broken/, fixed/, clean.html, special/, assets/ (+ make_images.py)
  ground_truth.json    Labeled issues for the rule-engine eval
  retrieval_golden.json   Golden questions for the retrieval eval
  results/             Committed eval results
tests/
```

## Roadmap

1. Foundation: crawler, rule engine, labeled benchmark, baseline eval (done)
2. WCAG knowledge base + RAG with citations (done)
3. Vision + measurement agents: alt text quality, contrast over images (done)
4. Interaction agent: keyboard and focus
5. Orchestrator, critic, report + eval harness v1
6. Fixer agent with re-scan verification and GitHub PRs
7. Live product: backend on Render, frontend on Vercel
8. LLMOps: tracing, CI eval gate, customer GitHub Action, scheduled rescans

## License notes

- axe-core is vendored under the Mozilla Public License 2.0 (see `src/parity/rules/vendor/axe-core-LICENSE.txt`).
- WCAG text is © W3C, used under the W3C Software and Document License (see `data/wcag/NOTICE.md`). Parity is not endorsed by W3C.
