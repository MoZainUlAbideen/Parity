"""Core data models shared by every part of Parity.

A scan produces one ScanReport. Each problem Parity finds is a Finding,
and every Finding says *how sure we are* (confidence) and *who found it*
(source), because honesty about certainty is the product's selling point.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class Impact(str, Enum):
    """How badly the issue hurts users (axe-core's own scale)."""

    critical = "critical"
    serious = "serious"
    moderate = "moderate"
    minor = "minor"
    unknown = "unknown"


class Confidence(str, Enum):
    """How certain Parity is that this is a real WCAG failure."""

    auto_verified = "auto-verified"  # deterministic rule engine says it fails
    ai_high = "ai-high-confidence"  # AI agent found it (later milestones)
    needs_review = "needs-review"  # a human should double-check


class Source(str, Enum):
    axe = "axe"
    parity_rules = "parity-rules"  # Parity's own deterministic checks (e.g. placeholder alt text)
    contrast_meter = "contrast-meter"  # pixel measurement of text over images
    vision_agent = "vision-agent"  # a vision model's judgment
    interaction_agent = "interaction-agent"


class Viewport(BaseModel):
    name: str
    width: int
    height: int
    is_mobile: bool = False


DESKTOP = Viewport(name="desktop", width=1366, height=900)
MOBILE = Viewport(name="mobile", width=390, height=844, is_mobile=True)
VIEWPORTS = {"desktop": DESKTOP, "mobile": MOBILE}


class NodeRef(BaseModel):
    """One element on the page that has the problem."""

    target: str  # CSS selector for the element
    html: str  # snippet of the element's markup
    failure_summary: str = ""
    evidence: str = ""  # how an agent or measurement reached its verdict
    suggestion: str = ""  # a concrete fix, e.g. proposed alt text


class Citation(BaseModel):
    """The exact WCAG rule a finding breaks, in W3C's own words."""

    sc: str  # "1.4.3"
    handle: str  # "Contrast (Minimum)"
    level: str  # "AA"
    guideline: str
    rule_text: str  # normative text of the success criterion
    goal: str = ""  # W3C "In brief" plain-language summary
    what_to_do: str = ""
    why_important: str = ""
    understanding_url: str
    normative_url: str
    obsolete: bool = False  # true for 4.1.1 Parsing, removed in WCAG 2.2


class Finding(BaseModel):
    rule_id: str
    description: str
    help: str
    help_url: str = ""
    impact: Impact = Impact.unknown
    wcag_criteria: list[str] = Field(default_factory=list)  # e.g. ["1.1.1"]
    wcag_level: str | None = None  # "A" or "AA"
    source: Source = Source.axe
    confidence: Confidence = Confidence.auto_verified
    viewports: list[str] = Field(default_factory=list)
    nodes: list[NodeRef] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)  # empty = best practice, not a WCAG rule


class PageSnapshot(BaseModel):
    """What the crawler captured for one viewport."""

    viewport: str
    requested_url: str
    final_url: str
    title: str
    lang: str | None
    screenshot_path: str | None
    aria_snapshot: str  # accessibility tree as the browser exposes it (YAML)
    dom_size: int  # number of elements, a rough complexity measure


class ScanSummary(BaseModel):
    total_findings: int
    by_impact: dict[str, int]
    by_confidence: dict[str, int]
    affected_elements: int


class Resolved(BaseModel):
    """A 'needs review' item an agent settled as passing, with its evidence."""

    rule_id: str
    target: str
    evidence: str


class ScanReport(BaseModel):
    url: str
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    engine: str
    duration_seconds: float
    snapshots: list[PageSnapshot]
    findings: list[Finding]
    summary: ScanSummary
    resolved: list[Resolved] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)  # which agents ran, e.g. ["contrast-meter"]
    notes: list[str] = Field(default_factory=list)  # agent problems worth knowing (quota, API errors)
