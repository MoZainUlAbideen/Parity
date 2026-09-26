"""Score scan results against human-labeled ground truth.

Kept separate from the browser code so the math is unit-testable.

Matching rule: a claimed finding matches a labeled issue when the rule id
AND the element selector are the same. Claimed = what we would tell a
customer is a real problem: "auto-verified" (rules, measurements) and
"ai-high-confidence" (agents). "needs-review" findings are reported but never
counted as detections or as false positives.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from parity.models import Confidence, Finding


class LabeledIssue(BaseModel):
    id: str
    rule: str
    selector: str
    wcag: str | None
    detectable_by: str  # "axe" or "ai"
    why: str = ""


class LabeledPage(BaseModel):
    page: str
    issues: list[LabeledIssue]
    negatives: list[str] = []  # suspicious-looking but correct elements (documentation)


class GroundTruth(BaseModel):
    version: int
    pages: list[LabeledPage]

    @classmethod
    def load(cls, path: Path) -> "GroundTruth":
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))


class Miss(BaseModel):
    page: str
    rule: str
    selector: str
    detectable_by: str


class FalsePositive(BaseModel):
    page: str
    rule: str
    selector: str


class PageResult(BaseModel):
    page: str
    true_positives: int
    false_positives: int
    labeled: int
    needs_review: int


class EvalResult(BaseModel):
    engine: str
    precision: float
    recall_rule_detectable: float
    recall_all: float
    recall_ai_only: float  # issues only judgment (AI or measurement) can find
    true_positives: int
    false_positives: int
    false_positives_on_clean: int
    labeled_total: int
    labeled_rule_detectable: int
    labeled_ai_only: int
    needs_review_total: int
    pages: list[PageResult]
    missed: list[Miss]
    false_positive_details: list[FalsePositive]


CLAIMED = {Confidence.auto_verified, Confidence.ai_high}


def _pairs(findings: list[Finding]) -> tuple[set[tuple[str, str]], int]:
    confirmed, review = set(), 0
    for f in findings:
        for n in f.nodes:
            if f.confidence in CLAIMED:
                confirmed.add((f.rule_id, n.target))
            else:
                review += 1
    return confirmed, review


def _ratio(num: int, den: int) -> float:
    # With nothing to find, perfect score by convention (and say so in reports).
    return round(num / den, 4) if den else 1.0


def score(truth: GroundTruth, findings_by_page: dict[str, list[Finding]], engine: str) -> EvalResult:
    tp = fp = fp_clean = review_total = 0
    labeled_total = labeled_rule = 0
    detected_rule = detected_ai = labeled_ai = 0
    pages, missed, fps = [], [], []

    for lp in truth.pages:
        confirmed, review = _pairs(findings_by_page.get(lp.page, []))
        expected = {(i.rule, i.selector): i for i in lp.issues}

        page_tp = len(confirmed & expected.keys())
        page_fp_pairs = confirmed - expected.keys()

        tp += page_tp
        fp += len(page_fp_pairs)
        if not lp.issues:
            fp_clean += len(page_fp_pairs)
        review_total += review
        labeled_total += len(lp.issues)
        labeled_rule += sum(1 for i in lp.issues if i.detectable_by == "axe")
        detected_rule += sum(1 for k in confirmed & expected.keys() if expected[k].detectable_by == "axe")
        labeled_ai += sum(1 for i in lp.issues if i.detectable_by == "ai")
        detected_ai += sum(1 for k in confirmed & expected.keys() if expected[k].detectable_by == "ai")

        for key, issue in expected.items():
            if key not in confirmed:
                missed.append(Miss(page=lp.page, rule=issue.rule, selector=issue.selector, detectable_by=issue.detectable_by))
        for rule, sel in sorted(page_fp_pairs):
            fps.append(FalsePositive(page=lp.page, rule=rule, selector=sel))

        pages.append(PageResult(page=lp.page, true_positives=page_tp, false_positives=len(page_fp_pairs), labeled=len(lp.issues), needs_review=review))

    return EvalResult(
        engine=engine,
        precision=_ratio(tp, tp + fp),
        recall_rule_detectable=_ratio(detected_rule, labeled_rule),
        recall_all=_ratio(tp, labeled_total),
        recall_ai_only=_ratio(detected_ai, labeled_ai),
        true_positives=tp,
        false_positives=fp,
        false_positives_on_clean=fp_clean,
        labeled_total=labeled_total,
        labeled_rule_detectable=labeled_rule,
        labeled_ai_only=labeled_ai,
        needs_review_total=review_total,
        pages=pages,
        missed=missed,
        false_positive_details=fps,
    )
