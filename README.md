# Parity

**Parity finds what's locking disabled users out of your website, explains it in plain words, and fixes it, with proof.**

About 1 in 6 people live with a disability, and 95.9% of the top million homepages fail automated WCAG checks (WebAIM Million 2026). Parity opens a page in a real browser, audits it the way a screen-reader user, a keyboard-only user, and a low-vision user would experience it, and reports each problem with the exact WCAG rule it breaks.

Every finding is labeled honestly:

| Label | Meaning |
|---|---|
| `auto-verified` | A deterministic rule engine confirmed it fails |
| `ai-high-confidence` | An AI agent found it (coming in milestones 3-4) |
| `needs-review` | Parity isn't sure; a human should check |

## Status: Milestone 2 (WCAG knowledge base + RAG)

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
- **Search in plain words**: `parity search "people keep tapping the wrong link on phones"` finds 2.5.8 Target Size. BM25 keyword search is always available; semantic search (bge-small, CPU) and hybrid fusion (RRF) are optional
- **Grounded answers**: `parity ask` answers from retrieved WCAG passages only. The model must copy exact quotes, code verifies each quote word for word against the passage, and unverified citations are dropped. If nothing survives, Parity says it couldn't verify an answer instead of guessing
- **Targets WCAG A/AA by default**, the level laws point to, so answers don't cite stricter AAA rules nobody is required to meet
- 95 tests, including a retrieval quality floor that fails CI if search gets worse

### Baseline: rule engine alone (milestone 1)

| Metric | Value |
|---|---|
| Precision | 100% |
| Recall on rule-detectable issues | 100% |
| **Recall on all labeled issues** | **68%** |
| False positives on fixed/clean pages | 0 |

The rules miss 6 of 19 issues, all judgment calls: a chart whose alt text is just "image", a placeholder used as the only label, white text over a background photo, two identical "Read more" links, and a clickable `<div>` a keyboard can't reach. Closing that gap is what the AI agents in the next milestones are for.

### Retrieval: does search find the right WCAG rule? (milestone 2)

54 golden questions, written in the asker's own words (not W3C's) so keyword overlap can't inflate scores.

| Method | Questions | Hit@1 | Hit@3 | Hit@5 | MRR |
|---|---|---|---|---|---|
| Keyword (BM25), all | 51 | 71% | 84% | 86% | 0.78 |
| Keyword, lay phrasing | 32 | 59% | 75% | 78% | 0.67 |
| Keyword, technical phrasing | 19 | 89% | 100% | 100% | 0.95 |
| Semantic / hybrid | | *run locally* | | | |

Keyword search is excellent when people use technical words and weak when they describe the problem in everyday language ("the site only works when I hold my tablet upright" should find 1.3.4 Orientation). That gap is what semantic search is for, and the eval measures whether it closes it.

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

# Evals
uv run parity baseline-eval
uv run parity retrieval-eval
```

Reports and screenshots go to `reports/`.

## Project layout

```
src/parity/
  models.py            Finding, Citation, ScanReport, confidence labels
  scanner.py           Real-browser crawl + axe per viewport, cited report
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
  fixtures/            broken/, fixed/, clean.html, special/
  ground_truth.json    Labeled issues for the rule-engine eval
  retrieval_golden.json   Golden questions for the retrieval eval
  results/             Committed eval results
tests/
```

## Roadmap

1. Foundation: crawler, rule engine, labeled benchmark, baseline eval (done)
2. WCAG knowledge base + RAG with citations (done)
3. Vision agent: alt text quality, contrast over images
4. Interaction agent: keyboard and focus
5. Orchestrator, critic, report + eval harness v1
6. Fixer agent with re-scan verification and GitHub PRs
7. Live product: backend on Render, frontend on Vercel
8. LLMOps: tracing, CI eval gate, customer GitHub Action, scheduled rescans

## License notes

- axe-core is vendored under the Mozilla Public License 2.0 (see `src/parity/rules/vendor/axe-core-LICENSE.txt`).
- WCAG text is © W3C, used under the W3C Software and Document License (see `data/wcag/NOTICE.md`). Parity is not endorsed by W3C.
