from pathlib import Path

from parity.eval.metrics import GroundTruth, LabeledIssue, LabeledPage, score
from parity.models import Confidence, Finding, NodeRef

GT_PATH = Path(__file__).resolve().parents[1] / "eval" / "ground_truth.json"


def f(rule, target, conf=Confidence.auto_verified):
    return Finding(rule_id=rule, description="", help="", confidence=conf, nodes=[NodeRef(target=target, html="")])


def truth():
    return GroundTruth(version=1, pages=[
        LabeledPage(page="broken.html", issues=[
            LabeledIssue(id="1", rule="image-alt", selector="#a", wcag="1.1.1", detectable_by="axe"),
            LabeledIssue(id="2", rule="label", selector="#b", wcag="4.1.2", detectable_by="axe"),
            LabeledIssue(id="3", rule="alt-text-uninformative", selector="#c", wcag="1.1.1", detectable_by="ai"),
        ]),
        LabeledPage(page="clean.html", issues=[]),
    ])


def test_perfect_rule_detection_but_ai_gap_shows_in_recall_all():
    r = score(truth(), {"broken.html": [f("image-alt", "#a"), f("label", "#b")], "clean.html": []}, engine="t")
    assert r.precision == 1.0
    assert r.recall_rule_detectable == 1.0
    assert round(r.recall_all, 2) == 0.67
    assert [m.rule for m in r.missed] == ["alt-text-uninformative"]


def test_wrong_element_is_both_a_miss_and_a_false_positive():
    r = score(truth(), {"broken.html": [f("image-alt", "#zzz")], "clean.html": []}, engine="t")
    assert r.true_positives == 0
    assert r.false_positives == 1


def test_false_positive_on_clean_page_is_counted_separately():
    r = score(truth(), {"broken.html": [], "clean.html": [f("region", "body")]}, engine="t")
    assert r.false_positives_on_clean == 1
    assert r.precision == 0.0


def test_needs_review_never_counts_as_detection_or_false_positive():
    r = score(truth(), {"broken.html": [f("image-alt", "#a", Confidence.needs_review)], "clean.html": []}, engine="t")
    assert r.true_positives == 0
    assert r.false_positives == 0
    assert r.needs_review_total == 1


def test_real_ground_truth_file_is_valid_and_consistent():
    gt = GroundTruth.load(GT_PATH)
    ids = [i.id for p in gt.pages for i in p.issues]
    assert len(ids) == len(set(ids)), "issue ids must be unique"
    for p in gt.pages:
        if p.page.startswith("fixed/") or p.page == "clean.html":
            assert p.issues == [], f"{p.page} must have no issues"
        for i in p.issues:
            assert i.detectable_by in {"axe", "ai"}
            assert i.selector, "every issue needs a selector"
    # every broken page has a fixed twin
    pages = {p.page for p in gt.pages}
    for p in pages:
        if p.startswith("broken/"):
            assert p.replace("broken/", "fixed/") in pages
