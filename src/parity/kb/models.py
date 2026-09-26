"""Data shapes for the WCAG knowledge base."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Section(str, Enum):
    """Which part of W3C's material a chunk came from."""

    normative = "normative"  # the success criterion itself (the actual rule)
    brief = "brief"  # W3C's plain-language "In brief": goal / what to do / why
    intent = "intent"
    benefits = "benefits"
    examples = "examples"
    techniques = "techniques"  # sufficient techniques and known failures


class Criterion(BaseModel):
    """One WCAG success criterion, e.g. 1.4.3 Contrast (Minimum)."""

    num: str  # "1.4.3"
    id: str  # "contrast-minimum" (W3C's slug)
    handle: str  # "Contrast (Minimum)"
    level: str  # "A", "AA", "AAA"
    versions: list[str]  # ["2.0", "2.1", "2.2"]
    guideline: str  # "1.4 Distinguishable"
    normative_text: str  # the rule, including its bullet list
    goal: str = ""
    what_to_do: str = ""
    why_important: str = ""
    failures: list[str] = Field(default_factory=list)  # e.g. ["F24: Failure of ..."]

    @property
    def obsolete(self) -> bool:
        """4.1.1 Parsing was removed in WCAG 2.2."""
        return "2.2" not in self.versions

    @property
    def understanding_url(self) -> str:
        return f"https://www.w3.org/WAI/WCAG22/Understanding/{self.id}.html"

    @property
    def normative_url(self) -> str:
        return f"https://www.w3.org/TR/WCAG22/#{self.id}"


class Chunk(BaseModel):
    chunk_id: str  # "1.4.3#intent-0"
    sc: str
    section: Section
    text: str
    url: str
