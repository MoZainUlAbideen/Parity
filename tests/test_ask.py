"""Grounding checks for `parity ask`, using a scripted fake LLM (no network)."""

import pytest

from parity.ask import ask, normalize
from parity.kb.retriever import Retriever
from parity.llm import LLMError

QUESTION = "What does 2.5.8 require?"  # exact lookup: P1 = normative, P2 = brief of 2.5.8


class FakeLLM:
    name = "fake"

    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def complete_json(self, system, user):
        self.prompts.append(user)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture(scope="module")
def retriever():
    return Retriever()


def test_real_quote_is_verified_and_answer_shown(retriever):
    llm = FakeLLM({"answerable": True, "answer": "Targets must be at least 24 by 24 CSS pixels (2.5.8).",
                   "citations": [{"passage": "P1", "quote": "at least 24 by 24 CSS pixels"}]})
    a = ask(QUESTION, retriever, llm)
    assert a.grounded
    assert a.answer.startswith("Targets must be")
    assert [(c.sc, c.passage) for c in a.citations] == [("2.5.8", "P1")]
    assert "[P1] 2.5.8 Target Size (Minimum)" in llm.prompts[0]


def test_invented_quote_is_rejected_and_answer_withheld(retriever):
    llm = FakeLLM({"answerable": True, "answer": "Targets must be 48 pixels.",
                   "citations": [{"passage": "P1", "quote": "targets must be at least 48 by 48 pixels"}]})
    a = ask(QUESTION, retriever, llm)
    assert not a.grounded
    assert "48" not in a.answer  # the unverified claim never reaches the user
    assert "2.5.8 Target Size (Minimum)" in a.answer
    assert a.rejected[0].reason == "quote not found in passage"


def test_mixed_citations_keep_only_the_verified_ones(retriever):
    llm = FakeLLM({"answerable": True, "answer": "ok",
                   "citations": [
                       {"passage": "P1", "quote": "at least 24 by 24 CSS pixels"},
                       {"passage": "P99", "quote": "a passage that was never provided"},
                       {"passage": "P2", "quote": "click"},
                   ]})
    a = ask(QUESTION, retriever, llm)
    assert a.grounded and len(a.citations) == 1
    assert sorted(r.reason for r in a.rejected) == ["no such passage", "quote too short to be evidence"]


def test_model_saying_unanswerable_gives_safe_fallback(retriever):
    llm = FakeLLM({"answerable": False, "answer": "Not covered.", "citations": []})
    a = ask(QUESTION, retriever, llm)
    assert not a.grounded and "couldn't verify" in a.answer


def test_garbage_citations_field_does_not_crash(retriever):
    llm = FakeLLM({"answer": "x", "citations": "P1"})
    a = ask(QUESTION, retriever, llm)
    assert not a.grounded


def test_provider_error_surfaces_as_llm_error(retriever):
    with pytest.raises(LLMError):
        ask(QUESTION, retriever, FakeLLM(RuntimeError("boom")))


def test_quote_matching_tolerates_curly_quotes_case_and_spacing():
    assert normalize("It’s  the  TARGET—size") == normalize("it's the target-size")


def test_rule_text_is_always_offered_even_when_search_found_only_examples(retriever):
    # Regression (2026-09-26): gpt-oss-120b cited only the *examples* section for
    # "How big do buttons need to be on mobile?" because the rule text of 2.5.8
    # was never in the passages. Now every criterion's rule comes first.
    llm = FakeLLM({"answerable": False, "answer": "", "citations": []})
    ask("How big do buttons need to be on mobile?", retriever, llm)
    prompt = llm.prompts[0]
    assert "2.5.8 Target Size (Minimum) (Level AA), section: normative" in prompt
    rule_pos = prompt.index("section: normative\nThe size of the target")
    assert "section: examples" not in prompt[:rule_pos].split("[P")[-1]  # rule is the criterion's first passage


def test_passages_are_not_duplicated(retriever):
    from parity.ask import build_passages

    hits = retriever.search("What does 2.5.8 require?")  # exact hit already carries the rule
    passages = build_passages(hits, retriever.kb)
    ids = [chunk.chunk_id for _, chunk in passages.values()]
    assert len(ids) == len(set(ids))
