"""BM25: the classic keyword-ranking formula behind most search engines.

A document scores high when it contains the query's words, especially rare
words (IDF), without rewarding long documents just for being long (b) or
repeating a word endlessly (k1). Written out here, ~40 lines, instead of a
library, so the scoring is fully visible and testable.
"""

from __future__ import annotations

import math
from collections import Counter

from parity.kb.text import tokenize


class BM25:
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.doc_tokens = [Counter(tokenize(d)) for d in documents]
        self.doc_len = [sum(t.values()) for t in self.doc_tokens]
        self.avg_len = sum(self.doc_len) / max(len(self.doc_len), 1)
        n = len(documents)
        df: Counter = Counter()
        for tokens in self.doc_tokens:
            df.update(tokens.keys())
        # BM25+ style IDF that never goes negative for very common words
        self.idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}

    def scores(self, query: str) -> list[float]:
        terms = tokenize(query)
        out = []
        for tokens, length in zip(self.doc_tokens, self.doc_len):
            s = 0.0
            for t in terms:
                tf = tokens.get(t, 0)
                if tf:
                    norm = tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self.avg_len))
                    s += self.idf.get(t, 0.0) * norm
            out.append(s)
        return out

    def rank(self, query: str, top_k: int | None = None) -> list[tuple[int, float]]:
        ranked = sorted(((i, s) for i, s in enumerate(self.scores(query)) if s > 0), key=lambda x: -x[1])
        return ranked[:top_k] if top_k else ranked
