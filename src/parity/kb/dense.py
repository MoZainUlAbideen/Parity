"""Semantic (dense) search: find passages by meaning, not shared words.

"My tap targets are tiny on phones" shares almost no words with W3C's
"The size of the target for pointer inputs is at least 24 by 24 CSS pixels",
so keyword search struggles. An embedding model maps both to nearby vectors.

Model: BAAI/bge-small-en-v1.5 via fastembed (ONNX, runs on CPU, ~130 MB,
fits a free-tier server). Optional install:  uv sync --extra dense

Chunk vectors are computed once and cached in .cache/ next to the project.
Anything with an `embed(texts) -> list[list[float]]` method works as an
embedder, which lets tests use a small fake instead of the real model.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Protocol

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
# bge models are trained with this prefix on queries (not on passages)
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedder:
    def __init__(self, model: str = DEFAULT_MODEL):
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # optional dependency
            raise RuntimeError("Dense search needs fastembed. Install it with:  uv sync --extra dense") from exc
        self.name = model
        self._model = TextEmbedding(model_name=model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.embed(texts, batch_size=64)]


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class DenseIndex:
    def __init__(self, embedder: Embedder, documents: list[str], cache_dir: Path | None = None):
        self.embedder = embedder
        self.vectors = self._load_or_embed(documents, cache_dir)

    def _load_or_embed(self, documents: list[str], cache_dir: Path | None) -> list[list[float]]:
        import json

        key = hashlib.sha256((self.embedder.name + "\n".join(documents)).encode("utf-8")).hexdigest()[:16]
        path = cache_dir / f"dense-{key}.json" if cache_dir else None
        if path and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        vectors = [_normalize(v) for v in self.embedder.embed(documents)]
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(vectors), encoding="utf-8")
        return vectors

    def rank(self, query: str, top_k: int | None = None) -> list[tuple[int, float]]:
        prefix = BGE_QUERY_PREFIX if "bge" in self.embedder.name.lower() else ""
        q = _normalize(self.embedder.embed([prefix + query])[0])
        sims = [(i, sum(a * b for a, b in zip(q, v))) for i, v in enumerate(self.vectors)]
        sims.sort(key=lambda x: -x[1])
        return sims[:top_k] if top_k else sims
