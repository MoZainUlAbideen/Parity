"""Attach WCAG citations to findings.

A finding from the rule engine already names its success criteria (axe tags
it, e.g. wcag143 -> 1.4.3). Citing is therefore an exact lookup, not a search:
deterministic, instant, and impossible to hallucinate. Search is only needed
when a human asks a free-form question (see parity.ask).
"""

from __future__ import annotations

from parity.kb.models import Criterion
from parity.kb.store import KnowledgeBase, load_kb
from parity.models import Citation, Finding


def citation_for(crit: Criterion) -> Citation:
    return Citation(
        sc=crit.num,
        handle=crit.handle,
        level=crit.level,
        guideline=crit.guideline,
        rule_text=crit.normative_text,
        goal=crit.goal,
        what_to_do=crit.what_to_do,
        why_important=crit.why_important,
        understanding_url=crit.understanding_url,
        normative_url=crit.normative_url,
        obsolete=crit.obsolete,
    )


class UnknownCriterionError(KeyError):
    pass


def cite(num: str, kb: KnowledgeBase | None = None) -> Citation:
    kb = kb or load_kb()
    crit = kb.criterion(num)
    if crit is None:
        raise UnknownCriterionError(f"WCAG 2.2 has no success criterion {num}")
    return citation_for(crit)


def cite_findings(findings: list[Finding], kb: KnowledgeBase | None = None) -> list[Finding]:
    """Return findings with citations filled in. Unknown numbers are skipped, never invented."""
    kb = kb or load_kb()
    for f in findings:
        f.citations = [citation_for(kb.criteria[n]) for n in f.wcag_criteria if n in kb.criteria]
    return findings
