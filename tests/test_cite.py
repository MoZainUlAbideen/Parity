import pytest

from parity.kb.cite import UnknownCriterionError, cite, cite_findings
from parity.models import Finding


def test_cite_contrast_uses_w3c_words():
    c = cite("1.4.3")
    assert c.handle == "Contrast (Minimum)" and c.level == "AA"
    assert "4.5:1" in c.rule_text
    assert c.why_important  # W3C's plain-language brief
    assert c.normative_url == "https://www.w3.org/TR/WCAG22/#contrast-minimum"
    assert c.understanding_url == "https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html"


def test_unknown_criterion_raises_instead_of_inventing():
    with pytest.raises(UnknownCriterionError):
        cite("9.9.9")


def test_cite_findings_attaches_all_known_criteria_and_skips_unknown():
    findings = [
        Finding(rule_id="link-name", description="", help="", wcag_criteria=["2.4.4", "4.1.2"]),
        Finding(rule_id="region", description="", help="", wcag_criteria=[]),  # best practice
        Finding(rule_id="weird", description="", help="", wcag_criteria=["9.9.9"]),
    ]
    out = cite_findings(findings)
    assert [c.sc for c in out[0].citations] == ["2.4.4", "4.1.2"]
    assert out[1].citations == []
    assert out[2].citations == []


def test_obsolete_parsing_criterion_is_flagged():
    assert cite("4.1.1").obsolete
