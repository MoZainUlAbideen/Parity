import json
from pathlib import Path

from parity.models import Confidence, Finding, Impact, NodeRef
from parity.rules.axe_runner import axe_version, merge_findings, normalize_axe_results

DATA = Path(__file__).parent / "data"


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def test_axe_is_vendored_and_versioned():
    assert axe_version().startswith("axe v4.")


def test_violation_becomes_auto_verified_finding():
    findings = normalize_axe_results(load("axe_raw_contrast.json"), "desktop")
    violation = next(f for f in findings if f.confidence == Confidence.auto_verified)
    assert violation.rule_id == "color-contrast"
    assert violation.wcag_criteria == ["1.4.3"]
    assert violation.wcag_level == "AA"
    assert violation.impact == Impact.serious
    assert [n.target for n in violation.nodes] == ["#faint"]
    assert violation.viewports == ["desktop"]


def test_incomplete_becomes_needs_review_not_a_confirmed_issue():
    # axe cannot compute contrast over a background image, so it says "not sure".
    findings = normalize_axe_results(load("axe_raw_contrast.json"), "desktop")
    review = [f for f in findings if f.confidence == Confidence.needs_review]
    assert [n.target for f in review for n in f.nodes] == ["#banner-text"]


def test_same_issue_on_two_viewports_is_merged_once():
    desktop = normalize_axe_results(load("axe_raw_contrast.json"), "desktop")
    mobile = normalize_axe_results(load("axe_raw_contrast_mobile.json"), "mobile")
    merged = merge_findings([desktop, mobile])
    confirmed = [f for f in merged if f.confidence == Confidence.auto_verified]
    assert len(confirmed) == 1
    assert confirmed[0].viewports == ["desktop", "mobile"]
    assert len(confirmed[0].nodes) == 1


def _f(rule, targets, conf, vp, impact=Impact.serious):
    return Finding(
        rule_id=rule, description="", help="", impact=impact, confidence=conf,
        viewports=[vp], nodes=[NodeRef(target=t, html="") for t in targets],
    )


def test_mobile_only_element_is_kept():
    merged = merge_findings([
        [_f("target-size", ["#a"], Confidence.auto_verified, "desktop")],
        [_f("target-size", ["#a", "#b"], Confidence.auto_verified, "mobile")],
    ])
    assert [n.target for n in merged[0].nodes] == ["#a", "#b"]


def test_violation_wins_over_needs_review_for_same_element():
    merged = merge_findings([
        [_f("color-contrast", ["#x"], Confidence.auto_verified, "desktop")],
        [_f("color-contrast", ["#x", "#y"], Confidence.needs_review, "mobile")],
    ])
    review = [f for f in merged if f.confidence == Confidence.needs_review]
    assert [n.target for n in review[0].nodes] == ["#y"]


def test_needs_review_dropped_entirely_when_all_elements_confirmed():
    merged = merge_findings([
        [_f("color-contrast", ["#x"], Confidence.auto_verified, "desktop")],
        [_f("color-contrast", ["#x"], Confidence.needs_review, "mobile")],
    ])
    assert all(f.confidence == Confidence.auto_verified for f in merged)


def test_sorted_confirmed_first_then_by_severity():
    merged = merge_findings([[
        _f("a-review", ["#1"], Confidence.needs_review, "desktop", Impact.critical),
        _f("b-minor", ["#2"], Confidence.auto_verified, "desktop", Impact.minor),
        _f("c-critical", ["#3"], Confidence.auto_verified, "desktop", Impact.critical),
    ]])
    assert [f.rule_id for f in merged] == ["c-critical", "b-minor", "a-review"]
