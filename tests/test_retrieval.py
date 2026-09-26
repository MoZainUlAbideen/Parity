import hashlib
import math

import pytest

from parity.kb.bm25 import BM25
from parity.kb.dense import DenseIndex
from parity.kb.retriever import Retriever, rrf
from parity.kb.text import tokenize


# ---------------------------------------------------------------- tokenizer / BM25


def test_tokenize_stems_and_drops_stopwords():
    assert tokenize("The Captions are captioned") == ["caption", "caption"]


def test_bm25_ranks_matching_doc_first_and_ignores_non_matches():
    bm = BM25(["video captions for deaf users", "color contrast of text", "keyboard focus order"])
    ranked = bm.rank("captioned videos")
    assert ranked[0][0] == 0
    assert all(i != 1 for i, _ in ranked)  # no shared words -> not returned


def test_bm25_rare_word_outweighs_common_word():
    docs = ["button button page", "page page page", "page contrast"]
    bm = BM25(docs)
    # "contrast" appears in 1 doc, "page" in all 3: the rare word should decide.
    assert bm.rank("page contrast")[0][0] == 2


def test_bm25_empty_query_returns_nothing():
    assert BM25(["anything"]).rank("the of and") == []


# ---------------------------------------------------------------- fusion


def test_rrf_rewards_agreement_between_rankers():
    fused = rrf([[1, 2, 3], [3, 1, 4]])
    assert [doc for doc, _ in fused][:2] == [1, 3]  # both lists rank 1 and 3 highly
    assert math.isclose(dict(fused)[4], 1 / 63)


# ---------------------------------------------------------------- retriever on the real KB


@pytest.fixture(scope="module")
def retriever():
    return Retriever()


def test_named_criterion_is_returned_first_by_exact_lookup(retriever):
    hits = retriever.search("what exactly does 2.5.8 require for mobile?")
    assert hits[0].sc == "2.5.8" and hits[0].exact_match
    assert {c.section.value for c in hits[0].evidence} == {"normative", "brief"}


def test_results_are_grouped_by_criterion(retriever):
    hits = retriever.search("captions for prerecorded video", top_k=5)
    scs = [h.sc for h in hits]
    assert len(scs) == len(set(scs))
    assert all(1 <= len(h.evidence) <= 3 for h in hits)
    assert all(e.sc == h.sc for h in hits for e in h.evidence)


def test_default_search_excludes_aaa(retriever):
    # 1.4.6 Contrast (Enhanced) is AAA; laws point to AA, so it must not appear.
    scs = [h.sc for h in retriever.search("enhanced contrast ratio 7:1 for text", top_k=10)]
    assert "1.4.6" not in scs
    assert "1.4.3" in scs


def test_all_levels_available_when_asked():
    r = Retriever(levels=None)
    assert "1.4.6" in [h.sc for h in r.search("enhanced contrast ratio 7:1 for text", top_k=10)]


def test_dense_methods_need_an_embedder(retriever):
    assert retriever.methods == ["bm25"]
    with pytest.raises(ValueError, match="embedding model"):
        retriever.search("anything", method="dense")


# ---------------------------------------------------------------- dense path with a stand-in model


class FakeEmbedder:
    """Deterministic hashed bag-of-words vectors: tests the dense plumbing without a model."""

    name = "fake-hash-64"

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        out = []
        for t in texts:
            v = [0.0] * 64
            for tok in tokenize(t):
                v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % 64] += 1.0
            out.append(v)
        return out


def test_dense_index_is_cached_and_reused(tmp_path):
    emb = FakeEmbedder()
    docs = ["video captions", "text contrast"]
    DenseIndex(emb, docs, cache_dir=tmp_path)
    assert len(list(tmp_path.glob("dense-*.json"))) == 1
    emb2 = FakeEmbedder()
    idx = DenseIndex(emb2, docs, cache_dir=tmp_path)
    assert emb2.calls == 0  # loaded from cache, model never called for passages
    assert idx.rank("captions video")[0][0] == 0


def test_hybrid_search_runs_and_returns_relevant_criterion(tmp_path):
    r = Retriever(embedder=FakeEmbedder(), cache_dir=tmp_path)
    assert r.methods == ["bm25", "dense", "hybrid"]
    for method in ("dense", "hybrid"):
        hits = r.search("captions for prerecorded video", method=method, top_k=5)
        assert "1.2.2" in [h.sc for h in hits]
