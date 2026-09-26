import json

from bs4 import BeautifulSoup

from parity.kb.build import _blocks, build_kb, clean, normative_text, pack, parse_understanding


def test_clean_strips_tags_entities_and_whitespace():
    assert clean('standard <abbr title="x">HTML</abbr>&nbsp;controls\n  work') == "standard HTML controls work"


def test_normative_text_includes_bullets_notes_and_paragraphs():
    sc = {
        "title": "Targets are at least 24 by 24 CSS pixels, except when:",
        "details": [
            {"type": "ulist", "items": [{"handle": "Spacing", "text": "Enough space around it;"}]},
            {"type": "note", "handle": "Note 1", "text": "Sliders count as one target."},
            {"type": "p", "text": "Exception: user agent controls."},
        ],
    }
    text = normative_text(sc)
    assert text.splitlines() == [
        "Targets are at least 24 by 24 CSS pixels, except when:",
        "- Spacing: Enough space around it;",
        "Note 1: Sliders count as one target.",
        "Exception: user agent controls.",
    ]


def test_pack_never_exceeds_limit_unless_single_block_is_bigger():
    blocks = ["a" * 300, "b" * 300, "c" * 300, "d" * 2000]
    chunks = pack(blocks, max_chars=700)
    assert chunks[0] == "a" * 300 + " " + "b" * 300
    assert chunks[1] == "c" * 300
    assert chunks[2] == "d" * 2000  # kept whole: never cut mid-sentence


def test_nested_blocks_are_not_duplicated_and_nothing_is_lost():
    html = """<section id="intent">
      <ul><li><p>Inside a list item paragraph.</p></li><li>Plain item.</li></ul>
      <table><tr><td><p>Cell paragraph.</p></td></tr></table>
      <p>Top-level paragraph.</p></section>"""
    blocks = _blocks(BeautifulSoup(html, "html.parser").section)
    assert blocks == ["Inside a list item paragraph.", "Plain item.", "Cell paragraph.", "Top-level paragraph."]


PAGE = """<html><body>
<section id="brief"><dl><dt>Goal</dt><dd>Make controls easier to activate.</dd>
<dt>What to do</dt><dd>Make targets big.</dd><dt>Why it's important</dt><dd>Small buttons are hard to click.</dd></dl></section>
<section id="intent"><h2>Intent</h2><p>Helps people with tremors.</p></section>
<section id="benefits"><ul><li>Touch screen users.</li></ul></section>
<section id="examples"><p>A 24px button.</p></section>
<section id="resources"><p>Ignored links.</p></section>
</body></html>"""


def test_parse_understanding_reads_brief_and_sections():
    u = parse_understanding(PAGE)
    assert u["goal"] == "Make controls easier to activate."
    assert u["what_to_do"] == "Make targets big."
    assert u["why_important"] == "Small buttons are hard to click."
    assert "Ignored links." not in json.dumps({k.value: v for k, v in u["sections"].items()})


def test_build_kb_end_to_end_on_a_tiny_source(tmp_path):
    raw = tmp_path / "raw"
    (raw / "understanding").mkdir(parents=True)
    quickref = {"principles": [{"guidelines": [{"num": "2.5", "handle": "Input Modalities", "successcriteria": [{
        "id": "target-size-minimum", "num": "2.5.8", "handle": "Target Size (Minimum)", "level": "AA",
        "versions": ["2.2"], "title": "Targets are at least 24 by 24 CSS pixels.", "details": [],
        "techniques": {"sufficient": [{"id": "C42", "technology": "css", "title": "Using min-height"}],
                       "failure": [{"id": "F1", "technology": "failures", "title": "Tiny icons"}]},
    }]}]}]}
    (raw / "wcag22.json").write_text(json.dumps(quickref), encoding="utf-8")
    (raw / "understanding" / "target-size-minimum.html").write_text(PAGE, encoding="utf-8")

    stats = build_kb(raw, tmp_path / "out")
    # techniques and failures are separate chunks
    assert stats == {"criteria": 1, "chunks": 7}

    crit = json.loads((tmp_path / "out" / "criteria.json").read_text(encoding="utf-8"))[0]
    assert crit["num"] == "2.5.8" and crit["guideline"] == "2.5 Input Modalities"
    assert crit["failures"] == ["F1: Tiny icons"]
    chunks = [json.loads(line) for line in (tmp_path / "out" / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [c["section"] for c in chunks] == ["normative", "brief", "intent", "benefits", "examples", "techniques", "techniques"]
    assert chunks[0]["url"] == "https://www.w3.org/TR/WCAG22/#target-size-minimum"
    assert chunks[5]["text"] == "Sufficient and advisory techniques: C42: Using min-height"
    assert chunks[6]["text"] == "Known failures: F1: Tiny icons"


def test_author_task_label_is_read_as_what_to_do():
    # Regression: W3C labels this "Author task" on 1.4.12 and 2.2.6; we lost it.
    page = PAGE.replace("<dt>What to do</dt>", "<dt>Author task</dt>")
    assert parse_understanding(page)["what_to_do"] == "Make targets big."
