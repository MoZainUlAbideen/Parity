"""Checks on the real, shipped knowledge base."""

from collections import Counter

from parity.kb.store import find_sc_numbers, load_kb


def test_all_87_wcag22_criteria_present():
    kb = load_kb()
    assert len(kb.criteria) == 87
    assert Counter(c.level for c in kb.criteria.values()) == {"A": 32, "AA": 24, "AAA": 31}


def test_every_criterion_has_rule_text_and_plain_language_brief():
    kb = load_kb()
    for num, crit in kb.criteria.items():
        sections = {c.section.value for c in kb.chunks_for(num)}
        assert {"normative", "brief", "intent"} <= sections, num
        assert crit.goal and crit.what_to_do and crit.why_important, num


def test_parsing_is_marked_obsolete_in_22():
    kb = load_kb()
    assert kb.criterion("4.1.1").obsolete
    assert not kb.criterion("1.4.3").obsolete


def test_new_22_criteria_exist():
    kb = load_kb()
    for num in ["2.4.11", "2.5.7", "2.5.8", "3.2.6", "3.3.7", "3.3.8"]:
        assert kb.criterion(num) and "2.2" in kb.criterion(num).versions


def test_chunk_ids_unique_and_urls_point_to_w3c():
    kb = load_kb()
    ids = [c.chunk_id for c in kb.chunks]
    assert len(ids) == len(set(ids))
    assert all(c.url.startswith("https://www.w3.org/") for c in kb.chunks)


def test_find_sc_numbers():
    assert find_sc_numbers("Does 1.4.3 or 2.5.8 apply? Not 12.3 or v1.2") == ["1.4.3", "2.5.8"]
    assert find_sc_numbers("1.4.10 reflow") == ["1.4.10"]
