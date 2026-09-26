"""Command-line interface.

    uv run parity scan https://example.com
    uv run parity scan http://localhost:8000/page.html --allow-local
    uv run parity baseline-eval

    uv run parity explain 1.4.3                 # a rule, in W3C's words
    uv run parity search "tap targets too small"   # which rules apply?
    uv run parity ask "how big must buttons be?"   # grounded answer (needs GROQ_API_KEY)
    uv run parity models                        # Groq models your key can use
    uv run parity retrieval-eval                # score search on the golden questions

    uv run parity kb fetch                      # re-download W3C sources
    uv run parity kb build                      # rebuild the knowledge base
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from playwright.async_api import Error as PlaywrightError
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from parity.models import Confidence, ScanReport
from parity.scanner import ScanBlockedError, scan_url
from parity.url_safety import UnsafeURLError

app = typer.Typer(add_completion=False, help="Parity: find and fix what locks disabled users out of a website.")
kb_app = typer.Typer(help="Build the WCAG knowledge base from W3C's sources.")
app.add_typer(kb_app, name="kb")
console = Console()

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "wcag" / "raw"
KB_DIR = Path(__file__).resolve().parent / "kb" / "data"
CACHE_DIR = REPO_ROOT / ".cache"

IMPACT_STYLE = {"critical": "bold red", "serious": "red", "moderate": "yellow", "minor": "cyan", "unknown": "dim"}


def print_report(report: ScanReport) -> None:
    s = report.summary
    console.print(f"\n[bold]{report.url}[/bold]  ({report.engine}, {report.duration_seconds}s)")
    console.print(
        f"{s.by_confidence.get(Confidence.auto_verified.value, 0)} confirmed issues on "
        f"{s.affected_elements} elements, "
        f"{s.by_confidence.get(Confidence.needs_review.value, 0)} need human review\n"
    )
    if not report.findings:
        console.print("[green]No automatically detectable issues found.[/green]")
        return
    table = Table(show_lines=False)
    table.add_column("Impact")
    table.add_column("Rule")
    table.add_column("WCAG")
    table.add_column("Elements", justify="right")
    table.add_column("Status")
    table.add_column("Viewports")
    for f in report.findings:
        table.add_row(
            f"[{IMPACT_STYLE[f.impact.value]}]{f.impact.value}[/]",
            f.rule_id,
            ", ".join(f.wcag_criteria) or "best practice",
            str(len(f.nodes)),
            f.confidence.value,
            ", ".join(f.viewports),
        )
    console.print(table)

    # One plain-language line per broken rule, straight from W3C's "In brief".
    seen = {}
    for f in report.findings:
        if f.confidence != Confidence.auto_verified:
            continue
        for c in f.citations:
            seen.setdefault(c.sc, c)
    if seen:
        console.print("\n[bold]Why these matter[/bold] (W3C, WCAG 2.2)")
        for sc in sorted(seen, key=lambda n: tuple(int(p) for p in n.split("."))):
            c = seen[sc]
            why = c.why_important or c.goal
            console.print(f"  [bold]{c.sc} {escape(c.handle)}[/bold] (Level {c.level}): {escape(why)}")


@app.command()
def scan(
    url: str = typer.Argument(..., help="Page to scan, e.g. https://example.com"),
    out: Path = typer.Option(Path("reports"), help="Folder for the JSON report and screenshots."),
    viewport: list[str] = typer.Option(["desktop", "mobile"], help="Viewports to test."),
    allow_local: bool = typer.Option(False, help="Allow localhost/private addresses (local testing only)."),
) -> None:
    """Scan one page and save a JSON report."""
    try:
        report = asyncio.run(scan_url(url, viewport, out_dir=out, allow_private=allow_local))
    except UnsafeURLError as exc:
        console.print(f"[red]Refused:[/red] {exc}")
        raise typer.Exit(code=2)
    except ScanBlockedError as exc:
        console.print(f"[yellow]Blocked:[/yellow] {escape(str(exc))}")
        raise typer.Exit(code=3)
    except PlaywrightError as exc:
        # Timeouts, DNS failures, pages that crash: a clean message, not a traceback.
        console.print(f"[red]Scan failed:[/red] {escape(str(exc).splitlines()[0])}")
        raise typer.Exit(code=1)
    print_report(report)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "report.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"\nSaved {path}")


@app.command("baseline-eval")
def baseline_eval(
    out: Path = typer.Option(Path("eval/results/baseline.json"), help="Where to write metrics."),
) -> None:
    """Score the rule engine alone against the labeled fixture pages."""
    from parity.eval.baseline import run_baseline

    result = asyncio.run(run_baseline())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    console.print("\n[bold]Baseline: axe-core alone vs ground truth[/bold]\n")
    t = Table()
    for col in ["Metric", "Value"]:
        t.add_column(col)
    t.add_row("Precision (confirmed findings that are real)", f"{result.precision:.0%}")
    t.add_row("Recall on rule-detectable issues", f"{result.recall_rule_detectable:.0%}")
    t.add_row("Recall on ALL labeled issues", f"{result.recall_all:.0%}")
    t.add_row("False positives on fixed/clean pages", str(result.false_positives_on_clean))
    console.print(t)
    if result.missed:
        console.print("\n[bold]Missed issues[/bold] (the gap AI agents must close):")
        for m in result.missed:
            console.print(f"  - {m.page}: {m.rule} on {m.selector}  " + escape(f"[{m.detectable_by}]"))
    console.print(f"\nSaved {out}")


# ---------------------------------------------------------------- knowledge base


def _make_retriever(dense: bool):
    from parity.kb.retriever import Retriever

    embedder = None
    if dense:
        from parity.kb.dense import FastEmbedder

        try:
            with console.status("Loading embedding model (first run downloads ~130 MB)..."):
                embedder = FastEmbedder()
        except Exception as exc:  # missing extra, no network, etc.
            console.print(f"[yellow]Semantic search unavailable, using keyword search only:[/yellow] {escape(str(exc))}")
    with console.status("Indexing WCAG passages..."):
        return Retriever(embedder=embedder, cache_dir=CACHE_DIR)


@kb_app.command("fetch")
def kb_fetch() -> None:
    """Download WCAG 2.2 sources from W3C's GitHub repositories into data/wcag/raw."""
    from parity.kb.sources import fetch_sources

    with console.status("Downloading from github.com/w3c ..."):
        stats = fetch_sources(RAW_DIR)
    console.print(f"Fetched {stats['criteria']} criteria and {stats['understanding_pages']} Understanding pages into {RAW_DIR}")


@kb_app.command("build")
def kb_build() -> None:
    """Parse the raw W3C files into criteria.json + chunks.jsonl."""
    from parity.kb.build import build_kb

    stats = build_kb(RAW_DIR, KB_DIR)
    console.print(f"Built knowledge base: {stats['criteria']} criteria, {stats['chunks']} passages -> {KB_DIR}")


@app.command()
def explain(sc: str = typer.Argument(..., help="Success criterion number, e.g. 1.4.3")) -> None:
    """Show a WCAG success criterion in W3C's own words."""
    from parity.kb.cite import UnknownCriterionError, cite

    try:
        c = cite(sc.strip())
    except UnknownCriterionError as exc:
        console.print(f"[red]{escape(str(exc.args[0]))}[/red]")
        raise typer.Exit(code=2)
    body = []
    if c.obsolete:
        body.append("[yellow]Obsolete: removed in WCAG 2.2.[/yellow]\n")
    if c.goal:
        body.append(f"[bold]Goal:[/bold] {escape(c.goal)}")
        body.append(f"[bold]What to do:[/bold] {escape(c.what_to_do)}")
        body.append(f"[bold]Why it's important:[/bold] {escape(c.why_important)}\n")
    body.append(f"[bold]The rule:[/bold]\n{escape(c.rule_text)}\n")
    body.append(f"[dim]{c.normative_url}\n{c.understanding_url}[/dim]")
    console.print(Panel("\n".join(body), title=f"{c.sc} {escape(c.handle)}  (Level {c.level}, {escape(c.guideline)})", expand=False))


@app.command()
def search(
    question: str = typer.Argument(..., help="Describe the problem in your own words"),
    top: int = typer.Option(5, help="How many criteria to show"),
    dense: bool = typer.Option(True, help="Use semantic search if the model is installed"),
) -> None:
    """Find the WCAG criteria that apply to a problem."""
    retriever = _make_retriever(dense)
    for i, h in enumerate(retriever.search(question, top_k=top), start=1):
        tag = " [exact]" if h.exact_match else ""
        console.print(f"[bold]{i}. {h.sc} {escape(h.handle)}[/bold] (Level {h.level}){tag}")
        best = h.evidence[0]
        console.print(f"   [dim]{best.section.value}:[/dim] {escape(best.text[:220])}{'...' if len(best.text) > 220 else ''}")


@app.command()
def ask(
    question: str = typer.Argument(..., help="An accessibility question"),
    dense: bool = typer.Option(True, help="Use semantic search if the model is installed"),
) -> None:
    """Answer a question from WCAG's text, with every quote verified."""
    from parity.ask import ask as run_ask
    from parity.llm import GroqLLM, LLMError

    try:
        llm = GroqLLM()
        retriever = _make_retriever(dense)
        with console.status(f"Asking {llm.name}..."):
            result = run_ask(question, retriever, llm)
    except LLMError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1)

    status = "[green]verified against WCAG text[/green]" if result.grounded else "[yellow]could not be verified[/yellow]"
    console.print(Panel(escape(result.answer), title=f"Answer ({status})", expand=False))
    for c in result.citations:
        console.print(f'  [bold]{c.sc} {escape(c.handle)}[/bold]: "{escape(c.quote)}"\n    [dim]{c.url}[/dim]')
    if result.rejected:
        console.print(f"\n[dim]{len(result.rejected)} citation(s) dropped because they failed verification:[/dim]")
        for r in result.rejected:
            console.print(f'  [dim]- {r.passage} "{escape(r.quote[:80])}": {r.reason}[/dim]')


@app.command()
def models() -> None:
    """List the Groq chat models your API key can use."""
    from parity.llm import GroqLLM, LLMError

    try:
        llm = GroqLLM()
        available = llm.list_models()
    except LLMError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1)
    console.print(f"Current model: [bold]{escape(llm.name)}[/bold]{'' if llm.name in available else ' [red](not available)[/red]'}\n")
    for m in available:
        console.print(f"  {escape(m)}")
    console.print("\nTo switch, add to .env:  PARITY_LLM_MODEL=<model>")


@app.command("retrieval-eval")
def retrieval_eval(
    out: Path = typer.Option(Path("eval/results/retrieval.json"), help="Where to write metrics."),
    dense: bool = typer.Option(True, help="Also evaluate semantic and hybrid search if the model is installed"),
) -> None:
    """Score WCAG search on the golden questions, per method."""
    import json

    from parity.eval.retrieval import KS, evaluate, load_golden

    golden = load_golden()
    retriever = _make_retriever(dense)
    results = []
    for method in retriever.methods:
        with console.status(f"Evaluating {method}..."):
            results.append(evaluate(retriever, method, golden))

    t = Table(title=f"WCAG retrieval, {len(golden)} golden questions (lay + technical; named reported separately)")
    t.add_column("Method")
    t.add_column("Questions", justify="right")
    for k in KS:
        t.add_column(f"Hit@{k}", justify="right")
    t.add_column("MRR", justify="right")
    for r in results:
        for label, s in [("all", r.overall)] + [(c, s) for c, s in r.by_category.items()]:
            t.add_row(f"{r.method} / {label}", str(s.n), *[f"{s.hit_at[k]:.0%}" for k in KS], f"{s.mrr:.2f}")
        t.add_section()
    console.print(t)

    best = max(results, key=lambda r: r.overall.mrr)
    misses = [q for q in best.questions if not q.first_hit_rank or q.first_hit_rank > 3]
    if misses:
        console.print(f"\n[bold]Not in top 3 with {best.method}[/bold]:")
        for q in misses:
            console.print(f"  {q.id} want {', '.join(q.relevant)}, got {', '.join(q.retrieved[:3])}  [dim]{escape(q.question)}[/dim]")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([r.model_dump() for r in results], indent=2), encoding="utf-8")
    console.print(f"\nSaved {out}")


def main() -> None:
    app()
