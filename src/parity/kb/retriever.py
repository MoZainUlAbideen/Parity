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
    def methods(self) -> list[str]:
        return ["bm25"] + (["dense", "hybrid"] if self.dense else [])

    def _chunk_ranking(self, query: str, method: Method) -> list[tuple[int, float]]:
        pool = 100  # rank this many chunks before grouping by criterion
        if method == "bm25":
            return self.bm25.rank(query, pool)
        if self.dense is None:
            raise ValueError(f"Method '{method}' needs an embedding model; install with: uv sync --extra dense")
        if method == "dense":
            return self.dense.rank(query, pool)
        bm = [i for i, _ in self.bm25.rank(query, pool)]
        de = [i for i, _ in self.dense.rank(query, pool)]
        return rrf([bm, de])[:pool]

    def search(self, query: str, top_k: int = 5, method: Method | None = None, evidence_per_hit: int = 3) -> list[Hit]:
        method = method or ("hybrid" if self.dense else "bm25")
        hits: dict[str, Hit] = {}

        # 1. Criteria named explicitly in the question come first.
        for num in find_sc_numbers(query):
            crit = self.kb.criterion(num)
            if crit and num not in hits:
                own = [c for c in self.kb.chunks_for(num) if c.section.value in ("normative", "brief")]
                hits[num] = Hit(sc=num, handle=crit.handle, level=crit.level, score=float("inf"), evidence=own, exact_match=True)

        # 2. Ranked passages, grouped by criterion (best passage decides the order).
        for idx, score in self._chunk_ranking(query, method):
            chunk = self.chunks[idx]
            crit = self.kb.criteria[chunk.sc]
            hit = hits.get(chunk.sc)
            if hit is None:
                hits[chunk.sc] = Hit(sc=chunk.sc, handle=crit.handle, level=crit.level, score=score, evidence=[chunk])
            elif not hit.exact_match and len(hit.evidence) < evidence_per_hit:
                hit.evidence.append(chunk)
        return list(hits.values())[:top_k]
