"""Retrieval eval: does search find the right WCAG criterion?

Metrics, computed per question at the criterion level:
  hit@k   the right criterion is in the top k results
  MRR     1 / rank of the first right criterion (0 if not in top 10)

Scored per method (bm25 / dense / hybrid) and per question category, so we
can see exactly where each method wins or loses. Run with:
    uv run parity retrieval-eval
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from parity.eval.fixture_server import REPO_ROOT
from parity.kb.retriever import Retriever

GOLDEN_PATH = REPO_ROOT / "eval" / "retrieval_golden.json"
KS = (1, 3, 5)
MRR_DEPTH = 10


class GoldenQuestion(BaseModel):
    id: str
    category: str
    question: str
    relevant: list[str]


class QuestionResult(BaseModel):
    id: str
    category: str
    question: str
    relevant: list[str]
    retrieved: list[str]
    first_hit_rank: int | None  # 1-based, None if not in top MRR_DEPTH


class MethodScores(BaseModel):
    n: int
    hit_at: dict[int, float]
    mrr: float


class RetrievalEvalResult(BaseModel):
    method: str
    overall: MethodScores  # lay + technical (named questions excluded: exact lookup would inflate it)
    by_category: dict[str, MethodScores]
    questions: list[QuestionResult]


def load_golden(path: Path = GOLDEN_PATH) -> list[GoldenQuestion]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [GoldenQuestion.model_validate(q) for q in data["questions"]]


def first_hit_rank(retrieved: list[str], relevant: list[str]) -> int | None:
    for rank, sc in enumerate(retrieved, start=1):
        if sc in relevant:
            return rank
    return None


def aggregate(results: list[QuestionResult]) -> MethodScores:
    n = len(results)
    if n == 0:
        return MethodScores(n=0, hit_at={k: 0.0 for k in KS}, mrr=0.0)
    hit_at = {k: round(sum(1 for r in results if r.first_hit_rank and r.first_hit_rank <= k) / n, 4) for k in KS}
    mrr = round(sum(1 / r.first_hit_rank for r in results if r.first_hit_rank) / n, 4)
    return MethodScores(n=n, hit_at=hit_at, mrr=mrr)


def evaluate(retriever: Retriever, method: str, golden: list[GoldenQuestion]) -> RetrievalEvalResult:
    results = []
    for q in golden:
        hits = retriever.search(q.question, top_k=MRR_DEPTH, method=method)
        retrieved = [h.sc for h in hits]
        results.append(QuestionResult(
            id=q.id, category=q.category, question=q.question, relevant=q.relevant,
            retrieved=retrieved, first_hit_rank=first_hit_rank(retrieved, q.relevant),
        ))
    categories = sorted({r.category for r in results})
    return RetrievalEvalResult(
        method=method,
        overall=aggregate([r for r in results if r.category != "named"]),
        by_category={c: aggregate([r for r in results if r.category == c]) for c in categories},
        questions=results,
    )
