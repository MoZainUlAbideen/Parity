"""Command-line interface.

    uv run parity scan https://example.com
    uv run parity scan http://localhost:8000/page.html --allow-local
    uv run parity baseline-eval
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from playwright.async_api import Error as PlaywrightError
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from parity.models import Confidence, ScanReport
from parity.scanner import ScanBlockedError, scan_url
from parity.url_safety import UnsafeURLError

app = typer.Typer(add_completion=False, help="Parity: find and fix what locks disabled users out of a website.")
console = Console()

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


def main() -> None:
    app()
