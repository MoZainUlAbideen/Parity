"""Find the WCAG success criteria (and the exact passages) that answer a question.

Three ways to rank, compared honestly in the retrieval eval:
  bm25    keyword match (always available, no model)
  dense   meaning match (needs the optional embedding model)
  hybrid  both, combined with Reciprocal Rank Fusion

Plus one shortcut: if the question names a criterion ("what does 1.4.3
require?"), that criterion goes first, by exact lookup. No ranking can beat
the user telling us.

Results are grouped by criterion, because a customer asks "which rule is
this?", not "which paragraph?". Each hit carries its best passages as evidence
for citations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from parity.kb.bm25 import BM25
from parity.kb.dense import DenseIndex, Embedder
from parity.kb.models import Chunk, Criterion
from parity.kb.store import KnowledgeBase, find_sc_numbers, load_kb

Method = Literal["bm25", "dense", "hybrid"]
DEFAULT_LEVELS = ("A", "AA")  # the conformance target laws point to (WCAG AA)
RRF_K = 60  # standard constant from the RRF paper (Cormack et al., 2009)


class Hit(BaseModel):
    sc: str
    handle: str
    level: str
    score: float
    evidence: list[Chunk]
    exact_match: bool = False  # the question named this criterion


def rrf(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion: each list votes 1/(k + rank) for its items."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: -x[1])


def index_text(chunk: Chunk, crit: Criterion) -> str:
    # Prefixing the criterion name gives every chunk its context
    # ("contextual chunk headers"): a bare paragraph from "examples" still
    # says which rule it belongs to.
    return f"{crit.num} {crit.handle}. {chunk.text}"


class Retriever:
    def __init__(
        self,
        kb: KnowledgeBase | None = None,
        embedder: Embedder | None = None,
        cache_dir: Path | None = None,
        levels: tuple[str, ...] | None = DEFAULT_LEVELS,
    ):
        self.kb = kb or load_kb()
        self.levels = levels
        self.chunks = [
            c for c in self.kb.chunks
            if levels is None or self.kb.criteria[c.sc].level in levels
        ]
        docs = [index_text(c, self.kb.criteria[c.sc]) for c in self.chunks]
        self.bm25 = BM25(docs)
        self.dense = DenseIndex(embedder, docs, cache_dir) if embedder else None

    @property
    def default_method(self) -> str:
        # Best measured method (eval/results/retrieval.json, 2026-09-26): dense beat
        # bm25 on hit@5 (92% vs 86%). Hybrid is re-measured after the fusion fix.
        return "dense" if self.dense else "bm25"

    @property
    def methods(self) -> list[str]:
        return ["bm25"] + (["dense", "hybrid"] if self.dense else [])

    def _chunk_ranking(self, query: str, method: str) -> list[tuple[int, float]]:
        pool = 100  # rank this many passages before grouping by criterion
        if method == "bm25":
            return self.bm25.rank(query, pool)
        if self.dense is None:
            raise ValueError(f"Method '{method}' needs an embedding model; install with: uv sync --extra dense")
        return self.dense.rank(query, pool)

    def _criterion_ranking(self, query: str, method: str) -> list[tuple[str, float, list[int]]]:
        """Criteria in rank order, each with its matching passage indices (best first).

        Hybrid fuses CRITERION rankings, not passage rankings. Regression
        (2026-09-26): passage-level fusion let criteria with many mediocre
        passages in both lists outrank the criterion one method put first
        ("hold my tablet upright": dense #1 1.3.4 Orientation fell out of the
        top 10). Fusing at the level we actually return fixes that.
        """
        if method in ("bm25", "dense"):
            order: dict[str, tuple[float, list[int]]] = {}
            for idx, score in self._chunk_ranking(query, method):
                sc = self.chunks[idx].sc
                if sc not in order:
                    order[sc] = (score, [idx])
                else:
                    order[sc][1].append(idx)
            return [(sc, score, idxs) for sc, (score, idxs) in order.items()]
        if method != "hybrid":
            raise ValueError(f"Unknown method '{method}'")
        per_method = [self._criterion_ranking(query, m) for m in ("bm25", "dense")]
        passages: dict[str, list[int]] = {}
        for ranking in per_method:
            for sc, _, idxs in ranking:
                passages.setdefault(sc, [])
                passages[sc] += [i for i in idxs if i not in passages[sc]]
        fused = rrf([[sc for sc, _, _ in ranking] for ranking in per_method])
        return [(sc, score, passages[sc]) for sc, score in fused]

    def search(self, query: str, top_k: int = 5, method: Method | None = None, evidence_per_hit: int = 3) -> list[Hit]:
        method = method or self.default_method
        hits: dict[str, Hit] = {}

        # 1. Criteria named explicitly in the question come first.
        for num in find_sc_numbers(query):
            crit = self.kb.criterion(num)
            if crit and num not in hits:
                own = [c for c in self.kb.chunks_for(num) if c.section.value in ("normative", "brief")]
                hits[num] = Hit(sc=num, handle=crit.handle, level=crit.level, score=float("inf"), evidence=own, exact_match=True)

        # 2. Ranked criteria, each with its best-matching passages as evidence.
        for sc, score, idxs in self._criterion_ranking(query, method):
            if sc in hits:
                continue
            crit = self.kb.criteria[sc]
            hits[sc] = Hit(sc=sc, handle=crit.handle, level=crit.level, score=score,
                           evidence=[self.chunks[i] for i in idxs[:evidence_per_hit]])
            if len(hits) >= top_k:
                break
        return list(hits.values())[:top_k]
