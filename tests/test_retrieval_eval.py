from parity.eval.retrieval import QuestionResult, aggregate, evaluate, first_hit_rank, load_golden
from parity.kb.retriever import Retriever
from parity.kb.store import load_kb


def test_first_hit_rank():
    assert first_hit_rank(["1.4.3", "2.5.8"], ["2.5.8"]) == 2
    assert first_hit_rank(["1.4.3"], ["2.5.8"]) is None


def q(rank):
    return QuestionResult(id="x", category="lay", question="", relevant=[], retrieved=[], first_hit_rank=rank)


def test_aggregate_math():
    s = aggregate([q(1), q(2), q(4), q(None)])
    assert s.hit_at == {1: 0.25, 3: 0.5, 5: 0.75}
    assert s.mrr == round((1 + 0.5 + 0.25) / 4, 4)


def test_golden_set_is_valid():
    kb = load_kb()
    golden = load_golden()
    ids = [g.id for g in golden]
    assert len(ids) == len(set(ids))
    for g in golden:
        assert g.category in {"lay", "technical", "named"}
        for sc in g.relevant:
            assert sc in kb.criteria, f"{g.id}: {sc} is not a WCAG 2.2 criterion"
            assert kb.criteria[sc].level in {"A", "AA"}, f"{g.id}: {sc} is AAA, outside Parity's target"


def test_keyword_search_quality_floor():
    """Eval gate: fails CI if a change makes search clearly worse than the recorded baseline.

    Baseline (2026-09-26, bm25): all hit@5 86%, technical hit@3 100%, lay hit@1 59%.
    Floors sit a little below, so normal noise passes but a real regression doesn't.
    """
    result = evaluate(Retriever(), "bm25", load_golden())
    assert result.overall.hit_at[5] >= 0.80
    assert result.by_category["technical"].hit_at[3] >= 0.90
    assert result.by_category["named"].hit_at[1] == 1.0
