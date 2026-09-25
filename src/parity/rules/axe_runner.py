"""Run axe-core inside a live page and turn its output into Parity Findings.

axe-core is the industry-standard open-source accessibility rule engine
(MPL-2.0, vendored in ./vendor). It is deterministic: same page, same result.
This is Parity's ground floor, it costs zero LLM tokens.

axe returns four buckets:
  violations   -> definite failures        -> Confidence.auto_verified
  incomplete   -> axe could not decide     -> Confidence.needs_review
  passes / inapplicable                    -> ignored here
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from typing import Any

from parity.models import Confidence, Finding, Impact, NodeRef, Source
from parity.wcag import parse_criteria, parse_level

# Only run rules tied to WCAG 2.0/2.1/2.2 A and AA, plus axe best practices.
DEFAULT_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]


@lru_cache(maxsize=1)
def axe_source() -> str:
    return files("parity.rules").joinpath("vendor/axe.min.js").read_text(encoding="utf-8")


def axe_version() -> str:
    # First line looks like: /*! axe v4.13.0
    first = axe_source().splitlines()[0]
    return first.replace("/*!", "").strip()


async def run_axe(page, tags: list[str] | None = None) -> dict[str, Any]:
    """Inject axe into a Playwright page and return its raw results."""
    await page.add_script_tag(content=axe_source())
    options = {"runOnly": {"type": "tag", "values": tags or DEFAULT_TAGS}, "resultTypes": ["violations", "incomplete"]}
    return await page.evaluate("async (opts) => await axe.run(document, opts)", options)


def _impact(value: str | None) -> Impact:
    try:
        return Impact(value) if value else Impact.unknown
    except ValueError:
        return Impact.unknown


def _target_to_selector(target: list) -> str:
    # axe targets are lists; nested lists mean shadow DOM / iframes.
    parts = []
    for t in target:
        parts.append(" >>> ".join(t) if isinstance(t, list) else str(t))
    return " | ".join(parts)


def _to_finding(rule: dict, confidence: Confidence, viewport: str) -> Finding:
    tags = rule.get("tags", [])
    return Finding(
        rule_id=rule["id"],
        description=rule.get("description", ""),
        help=rule.get("help", ""),
        help_url=rule.get("helpUrl", ""),
        impact=_impact(rule.get("impact")),
        wcag_criteria=parse_criteria(tags),
        wcag_level=parse_level(tags),
        source=Source.axe,
        confidence=confidence,
        viewports=[viewport],
        nodes=[
            NodeRef(
                target=_target_to_selector(n.get("target", [])),
                html=(n.get("html") or "")[:500],
                failure_summary=n.get("failureSummary") or "",
            )
            for n in rule.get("nodes", [])
        ],
    )


def normalize_axe_results(raw: dict[str, Any], viewport: str) -> list[Finding]:
    findings = [_to_finding(r, Confidence.auto_verified, viewport) for r in raw.get("violations", [])]
    findings += [_to_finding(r, Confidence.needs_review, viewport) for r in raw.get("incomplete", [])]
    return findings


def merge_findings(per_viewport: list[list[Finding]]) -> list[Finding]:
    """Combine findings from several viewports.

    The same rule failing on the same element in desktop and mobile is ONE
    problem, not two. Elements that fail only on mobile keep just 'mobile'.
    A violation always wins over a needs-review for the same rule.
    """
    merged: dict[tuple[str, str], Finding] = {}
    node_viewports: dict[tuple[str, str, str], set[str]] = {}

    for findings in per_viewport:
        for f in findings:
            key = (f.rule_id, f.confidence.value)
            if key not in merged:
                merged[key] = f.model_copy(deep=True, update={"nodes": [], "viewports": []})
            m = merged[key]
            for vp in f.viewports:
                if vp not in m.viewports:
                    m.viewports.append(vp)
            for n in f.nodes:
                nk = (f.rule_id, f.confidence.value, n.target)
                if nk not in node_viewports:
                    node_viewports[nk] = set()
                    m.nodes.append(n)
                node_viewports[nk].update(f.viewports)

    # Drop needs-review entries whose elements are already definite violations.
    result = []
    for (rule_id, conf), f in merged.items():
        if conf == Confidence.needs_review.value:
            violation = merged.get((rule_id, Confidence.auto_verified.value))
            if violation:
                known = {n.target for n in violation.nodes}
                f.nodes = [n for n in f.nodes if n.target not in known]
                if not f.nodes:
                    continue
        result.append(f)

    impact_rank = {i: r for r, i in enumerate(Impact)}
    result.sort(key=lambda f: (f.confidence != Confidence.auto_verified, impact_rank[f.impact], f.rule_id))
    return result
