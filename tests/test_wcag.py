from parity.wcag import parse_criteria, parse_level


def test_three_digit_criterion():
    assert parse_criteria(["cat.text-alternatives", "wcag2a", "wcag111"]) == ["1.1.1"]


def test_two_digit_last_part_like_1_4_10_and_2_5_8():
    assert parse_criteria(["wcag1410", "wcag258"]) == ["1.4.10", "2.5.8"]


def test_sorted_numerically_not_alphabetically():
    # Alphabetical would put 1.4.10 before 1.4.3
    assert parse_criteria(["wcag1410", "wcag143"]) == ["1.4.3", "1.4.10"]


def test_duplicates_removed():
    assert parse_criteria(["wcag412", "wcag412"]) == ["4.1.2"]


def test_levels():
    assert parse_level(["wcag2a", "wcag111"]) == "A"
    assert parse_level(["wcag2aa", "wcag143"]) == "AA"
    assert parse_level(["wcag21aa", "wcag1410"]) == "AA"
    assert parse_level(["wcag22aa", "wcag258"]) == "AA"


def test_criterion_tag_is_not_mistaken_for_level():
    # "wcag111" must never be read as a level tag
    assert parse_level(["wcag111"]) is None


def test_best_practice_has_no_level_or_criteria():
    tags = ["cat.semantics", "best-practice"]
    assert parse_level(tags) is None
    assert parse_criteria(tags) == []
