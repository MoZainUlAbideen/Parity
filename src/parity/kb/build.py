"""Turn W3C's raw WCAG files into a searchable, citable knowledge base.

Input  (data/wcag/raw/):      wcag22.json + understanding/<id>.html
Output (src/parity/kb/data/): criteria.json + chunks.jsonl

Chunking follows W3C's own structure, so every citation can say exactly
where its words came from:
  normative   the success criterion text itself (the rule)
  brief       W3C's plain-language "In brief" (goal / what to do / why)
  intent      what the rule is for
  benefits    who it helps
  examples    concrete examples
  techniques  sufficient techniques and documented failures

Long sections are split on paragraph boundaries into pieces of at most
MAX_CHARS, so a chunk is always whole sentences, never cut mid-word.

Run:  uv run parity kb build
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from parity.kb.models import Chunk, Criterion, Section
from parity.kb.sources import iter_criteria

MAX_CHARS = 900
KEEP_SECTIONS = [Section.intent, Section.benefits, Section.examples]

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean(text: str) -> str:
    """Strip HTML tags and entities, collapse whitespace."""
    return _WS.sub(" ", html.unescape(_TAG.sub("", text or ""))).strip()


def normative_text(sc: dict) -> str:
    parts = [clean(sc["title"])]
    for d in sc.get("details", []):
        if d["type"] == "ulist":
            for item in d["items"]:
                handle = clean(item.get("handle", ""))
                parts.append(f"- {handle}: {clean(item['text'])}" if handle else f"- {clean(item['text'])}")
        elif d["type"] == "note":
            parts.append(f"{clean(d.get('handle') or 'Note')}: {clean(d['text'])}")
        else:
            parts.append(clean(d["text"]))
    return "\n".join(p for p in parts if p)


def _technique_lines(techniques: dict) -> tuple[list[str], list[str]]:
    """Return (sufficient/advisory technique lines, failure lines)."""
    good, failures = [], []

    def walk(node, bucket):
        if isinstance(node, list):
            for x in node:
                walk(x, bucket)
        elif isinstance(node, dict):
            if "id" in node and "title" in node and "technology" in node:
                line = f"{node['id']}: {clean(node['title'])}"
                if line not in bucket:
                    bucket.append(line)
            for key in ("techniques", "groups", "and", "using"):
                if key in node:
                    walk(node[key], bucket)

    walk(techniques.get("sufficient", []), good)
    walk(techniques.get("advisory", []), good)
    walk(techniques.get("failure", []), failures)
    return good, failures


BLOCK_TAGS = ["h3", "h4", "p", "li", "dt", "dd", "td", "th", "figcaption", "pre", "blockquote"]


def _blocks(section_el) -> list[str]:
    """Paragraph-sized text blocks from a section, headings kept as context.

    W3C nests blocks (a <p> inside an <li>, a <p> inside a <td>). We keep only
    the OUTERMOST block and skip everything inside it, so no sentence is lost
    and none is counted twice.
    """
    blocks, taken = [], set()
    for el in section_el.find_all(BLOCK_TAGS):
        if any(id(parent) in taken for parent in el.parents):
            continue
        taken.add(id(el))
        text = clean(el.get_text(" "))
        if text:
            blocks.append(text)
    return blocks


def pack(blocks: list[str], max_chars: int = MAX_CHARS) -> list[str]:
    """Greedily join blocks into chunks of at most max_chars (a single long block stays whole)."""
    chunks, current = [], ""
    for b in blocks:
        if current and len(current) + 1 + len(b) > max_chars:
            chunks.append(current)
            current = b
        else:
            current = f"{current} {b}".strip()
    if current:
        chunks.append(current)
    return chunks


def parse_understanding(page_html: str) -> dict[str, object]:
    from bs4 import BeautifulSoup  # dev dependency, only needed to (re)build the KB

    soup = BeautifulSoup(page_html, "html.parser")
    out: dict[str, object] = {"goal": "", "what_to_do": "", "why_important": "", "sections": {}}

    brief = soup.find("section", id="brief")
    if brief:
        for dt in brief.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            label, value = clean(dt.get_text()).lower(), clean(dd.get_text()) if dd else ""
            if label.startswith("goal"):
                out["goal"] = value
            elif label.startswith(("what to do", "author task")):  # W3C uses both labels
                out["what_to_do"] = value
            elif label.startswith("why"):
                out["why_important"] = value

    for section in KEEP_SECTIONS:
        el = soup.find("section", id=section.value)
        if el:
            out["sections"][section] = _blocks(el)
    return out


def build_kb(raw_dir: Path, out_dir: Path) -> dict[str, int]:
    quickref = json.loads((raw_dir / "wcag22.json").read_text(encoding="utf-8"))
    criteria: list[Criterion] = []
    chunks: list[Chunk] = []

    for guideline, sc in iter_criteria(quickref):
        page = (raw_dir / "understanding" / f"{sc['id']}.html").read_text(encoding="utf-8")
        u = parse_understanding(page)
        good, failures = _technique_lines(sc.get("techniques", {}))

        crit = Criterion(
            num=sc["num"],
            id=sc["id"],
            handle=clean(sc["handle"]),
            level=sc["level"],
            versions=sc["versions"],
            guideline=f"{guideline['num']} {clean(guideline['handle'])}",
            normative_text=normative_text(sc),
            goal=u["goal"],
            what_to_do=u["what_to_do"],
            why_important=u["why_important"],
            failures=failures,
        )
        criteria.append(crit)

        def add(section: Section, texts: list[str], url: str) -> None:
            for i, t in enumerate(texts):
                chunks.append(Chunk(chunk_id=f"{crit.num}#{section.value}-{i}", sc=crit.num, section=section, text=t, url=url))

        add(Section.normative, [crit.normative_text], crit.normative_url)
        brief = " ".join(
            s for s in [
                f"Goal: {crit.goal}" if crit.goal else "",
                f"What to do: {crit.what_to_do}" if crit.what_to_do else "",
                f"Why it's important: {crit.why_important}" if crit.why_important else "",
            ] if s
        )
        if brief:
            add(Section.brief, [brief], crit.understanding_url + "#brief")
        for section in KEEP_SECTIONS:
            add(section, pack(u["sections"].get(section, [])), f"{crit.understanding_url}#{section.value}")
        tech_blocks = ([f"Sufficient and advisory techniques: {'; '.join(good)}"] if good else []) + (
            [f"Known failures: {'; '.join(failures)}"] if failures else []
        )
        # Technique lists can be long; split on '; ' boundaries.
        tech_texts = []
        for block in tech_blocks:
            head, _, body = block.partition(": ")
            tech_texts += [f"{head}: {piece}" for piece in pack(body.split("; "), MAX_CHARS)]
        add(Section.techniques, tech_texts, crit.understanding_url + "#techniques")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "criteria.json").write_text(
        json.dumps([c.model_dump() for c in criteria], indent=1, ensure_ascii=False), encoding="utf-8"
    )
    with (out_dir / "chunks.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for c in chunks:
            f.write(c.model_dump_json() + "\n")
    return {"criteria": len(criteria), "chunks": len(chunks)}
