"""Load the built knowledge base (shipped inside the package)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files

from pydantic import BaseModel

from parity.kb.models import Chunk, Criterion

SC_NUMBER = re.compile(r"\b([1-4])\.(\d{1,2})\.(\d{1,2})\b")


class KnowledgeBase(BaseModel):
    criteria: dict[str, Criterion]  # keyed by "1.4.3"
    chunks: list[Chunk]

    def criterion(self, num: str) -> Criterion | None:
        return self.criteria.get(num)

    def chunks_for(self, num: str) -> list[Chunk]:
        return [c for c in self.chunks if c.sc == num]


@lru_cache(maxsize=1)
def load_kb() -> KnowledgeBase:
    data = files("parity.kb").joinpath("data")
    criteria = [Criterion.model_validate(c) for c in json.loads(data.joinpath("criteria.json").read_text(encoding="utf-8"))]
    chunks = [
        Chunk.model_validate_json(line)
        for line in data.joinpath("chunks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return KnowledgeBase(criteria={c.num: c for c in criteria}, chunks=chunks)


def find_sc_numbers(text: str) -> list[str]:
    """'Does 1.4.3 apply?' -> ['1.4.3']"""
    return [".".join(m.groups()) for m in SC_NUMBER.finditer(text)]
