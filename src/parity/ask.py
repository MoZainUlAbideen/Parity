"""Answer accessibility questions from WCAG's own text, with verified quotes.

Pipeline:
  1. retrieve the most relevant WCAG passages
  2. ask the LLM to answer ONLY from those passages, in plain words, and to
     back every claim with a short quote copied exactly from a passage
  3. VERIFY each quote in code: it must appear word for word in the passage
     it claims to come from. Quotes that don't check out are dropped.
  4. if no citation survives, don't show the model's answer as fact: say we
     couldn't verify it and point to the likeliest criteria instead

Step 3 is what makes this safe to put in front of customers: a model can
invent a convincing-sounding rule, but it cannot fake a substring match.
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, Field

from parity.kb.models import Chunk, Section
from parity.kb.retriever import Hit, Retriever
from parity.kb.store import KnowledgeBase
from parity.llm import JsonLLM, LLMError

MIN_QUOTE_WORDS = 4  # "the target" is not evidence

SYSTEM_PROMPT = """You are Parity's accessibility assistant. You explain WCAG 2.2 to website owners and developers in plain, friendly language.

Rules:
- Answer ONLY using the numbered passages provided. They are official W3C text.
- Back every important claim with a citation: the passage id and a short quote (a phrase or sentence, at least 4 words) copied EXACTLY, character for character, from that passage.
- Passages from the "normative" section are the rule itself; other sections explain or illustrate it. When a normative passage supports a claim about what is required, quote the normative passage.
- Mention the success criterion number and name (for example "1.4.3 Contrast (Minimum)") when you refer to a rule.
- If the passages do not contain the answer, set "answerable" to false and say so. Never use outside knowledge to fill gaps.
- Keep the answer under 150 words.

Reply with JSON only:
{"answerable": true, "answer": "...", "citations": [{"passage": "P1", "quote": "exact words from P1"}]}"""


class VerifiedCitation(BaseModel):
    passage: str
    sc: str
    handle: str
    quote: str
    url: str


class RejectedCitation(BaseModel):
    passage: str
    quote: str
    reason: str


class Answer(BaseModel):
    question: str
    grounded: bool
    answer: str
    citations: list[VerifiedCitation] = Field(default_factory=list)
    rejected: list[RejectedCitation] = Field(default_factory=list)
    retrieved: list[str] = Field(default_factory=list)  # criteria the answer could draw on
    model: str = ""


def normalize(text: str) -> str:
    """Compare quotes fairly: unify curly quotes/dashes, case and whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip().lower()


def build_passages(hits: list[Hit], kb: KnowledgeBase, max_passages: int = 10) -> dict[str, tuple[Hit, Chunk]]:
    """Each criterion contributes its RULE TEXT first, then its best-matching passages.

    Search alone may surface only examples or intent; an example shows one
    passing case, but only the rule says what is required. So the rule always
    goes in, and the model is told to quote it when it supports the claim.
    """
    passages: dict[str, tuple[Hit, Chunk]] = {}
    for hit in hits:
        rule = [c for c in kb.chunks_for(hit.sc) if c.section == Section.normative]
        seen = set()
        for chunk in rule + hit.evidence:
            if chunk.chunk_id in seen:
                continue
            seen.add(chunk.chunk_id)
            if len(passages) >= max_passages:
                return passages
            passages[f"P{len(passages) + 1}"] = (hit, chunk)
    return passages


def format_passages(passages: dict[str, tuple[Hit, Chunk]]) -> str:
    return "\n\n".join(
        f"[{pid}] {hit.sc} {hit.handle} (Level {hit.level}), section: {chunk.section.value}\n{chunk.text}"
        for pid, (hit, chunk) in passages.items()
    )


def verify(raw_citations: list, passages: dict[str, tuple[Hit, Chunk]]) -> tuple[list[VerifiedCitation], list[RejectedCitation]]:
    good, bad = [], []
    for c in raw_citations if isinstance(raw_citations, list) else []:
        pid = str(c.get("passage", "")).strip().strip("[]") if isinstance(c, dict) else ""
        quote = str(c.get("quote", "")).strip().strip('"') if isinstance(c, dict) else ""
        if pid not in passages:
            bad.append(RejectedCitation(passage=pid, quote=quote, reason="no such passage"))
        elif len(quote.split()) < MIN_QUOTE_WORDS:
            bad.append(RejectedCitation(passage=pid, quote=quote, reason="quote too short to be evidence"))
        elif normalize(quote) not in normalize(passages[pid][1].text):
            bad.append(RejectedCitation(passage=pid, quote=quote, reason="quote not found in passage"))
        else:
            hit, chunk = passages[pid]
            good.append(VerifiedCitation(passage=pid, sc=hit.sc, handle=hit.handle, quote=quote, url=chunk.url))
    return good, bad


def fallback_answer(hits: list[Hit]) -> str:
    if not hits:
        return "I couldn't find anything about this in WCAG 2.2."
    top = ", ".join(f"{h.sc} {h.handle}" for h in hits[:3])
    return f"I couldn't verify an answer from the WCAG text. The most relevant criteria look like: {top}."


def ask(question: str, retriever: Retriever, llm: JsonLLM, top_k: int = 4) -> Answer:
    hits = retriever.search(question, top_k=top_k)
    retrieved = [h.sc for h in hits]
    if not hits:
        return Answer(question=question, grounded=False, answer=fallback_answer(hits), model=llm.name)

    passages = build_passages(hits, retriever.kb)
    user = f"Question: {question}\n\nPassages:\n\n{format_passages(passages)}"
    try:
        out = llm.complete_json(SYSTEM_PROMPT, user)
    except LLMError:
        raise
    except Exception as exc:  # malformed provider output shouldn't crash the product
        raise LLMError(f"LLM call failed: {exc}") from exc

    good, bad = verify(out.get("citations", []), passages)
    answerable = bool(out.get("answerable", True))
    grounded = answerable and len(good) > 0
    text = str(out.get("answer", "")).strip()
    return Answer(
        question=question,
        grounded=grounded,
        answer=text if grounded else fallback_answer(hits),
        citations=good,
        rejected=bad,
        retrieved=retrieved,
        model=llm.name,
    )
