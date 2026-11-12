"""Tests for Studio 2 lab 03. All offline: vectors ship in data/vectors.json.

Run:  pytest studio-2/03-hybrid-retrieval -q
The optional cross-encoder test runs only if sentence-transformers is installed.
"""
from __future__ import annotations

import math

import pytest

import starter as lab

TINY = {
    "a": "error vpn-719 vpn certificate expired",
    "b": "vpn client drops on hotel wifi",
    "c": "password reset needs a code",
    "d": "certificate certificate certificate renewal renewal policy for the vpn gateway servers",
}


@pytest.fixture(scope="module")
def data():
    return lab.load_data()


@pytest.fixture(scope="module")
def configs(data):
    corpus, queries, vectors = data
    return lab.run_all(corpus, queries, vectors)


def qrels_for(queries, qtype=None):
    return {q["id"]: set(q["relevant"]) for q in queries if qtype is None or q["type"] == qtype}


# ---------------------------------------------------------------- BM25


def test_tokenizer_keeps_identifiers():
    assert lab.tokenize("Error VPN-719, see PO-2026-01182.") == ["error", "vpn-719", "see", "po-2026-01182"]


def test_index_statistics():
    idx = lab.BM25(TINY)
    assert idx.n_docs == 4
    assert idx.lengths["a"] == 5 and idx.lengths["d"] == 11
    assert math.isclose(idx.avgdl, (5 + 6 + 5 + 11) / 4)
    assert idx.postings["certificate"] == {"a": 1, "d": 3}
    assert idx.postings["vpn"] == {"a": 1, "b": 1, "d": 1}


def test_idf_is_lucene_form_and_positive():
    idx = lab.BM25(TINY)
    assert math.isclose(idx.idf("vpn"), math.log(1 + (4 - 3 + 0.5) / (3 + 0.5)))
    assert idx.idf("vpn") > 0, "a term in most documents still gets a positive idf"
    assert idx.idf("vpn-719") > idx.idf("certificate") > idx.idf("vpn"), "rarer terms weigh more"


def test_score_matches_formula():
    idx = lab.BM25(TINY)
    tf, dl, avgdl = 3, 11, 6.75
    expected = idx.idf("certificate") * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * dl / avgdl))
    assert math.isclose(idx.score("certificate", "d"), expected, rel_tol=1e-9)
    assert idx.score("password", "a") == 0.0


def test_parameters_do_what_they_claim():
    flat = lab.BM25(TINY, b=0.0)
    one = {"x": "alpha beta", "y": "alpha beta gamma delta epsilon zeta"}
    assert math.isclose(lab.BM25(one, b=0.0).score("alpha", "x"), lab.BM25(one, b=0.0).score("alpha", "y")), (
        "b = 0 switches off length normalization"
    )
    assert lab.BM25(one).score("alpha", "x") > lab.BM25(one).score("alpha", "y"), "with b > 0 the shorter doc wins"
    binary = lab.BM25({"x": "cat", "y": "cat cat cat"}, k1=0.0, b=0.0)
    assert math.isclose(binary.score("cat", "x"), binary.score("cat", "y")), "k1 = 0 counts presence only"
    sat = lab.BM25({"x": "cat dog", "y": "cat cat cat cat cat cat cat cat cat cat"}, b=0.0)
    assert sat.score("cat", "y") < 2.2 * sat.idf("cat"), "term frequency saturates below (k1 + 1) * idf"
    assert flat.k1 == 1.2 and flat.b == 0.0


def test_search_returns_only_matching_docs_sorted():
    idx = lab.BM25(TINY)
    results = idx.search("vpn-719 certificate", k=10)
    assert [d for d, _ in results] == ["a", "d"]
    assert results[0][1] >= results[1][1]
    assert idx.search("quarterly forecast") == []
    assert len(idx.search("vpn", k=2)) == 2


# ---------------------------------------------------------------- vectors


def test_cosine_and_vector_search():
    assert math.isclose(lab.cosine([1, 0], [2, 0]), 1.0)
    assert math.isclose(lab.cosine([1, 0], [0, 3]), 0.0, abs_tol=1e-12)
    assert lab.cosine([0, 0], [1, 1]) == 0.0
    docs = {"n": [0.0, 1.0], "e": [1.0, 0.0], "ne": [0.7071, 0.7071]}
    assert [d for d, _ in lab.vector_search([1.0, 0.1], docs, k=2)] == ["e", "ne"]


# ---------------------------------------------------------------- fusion


def test_rrf_values_and_ties():
    fused = lab.rrf([["a", "b", "c"], ["c", "a", "d"]])
    assert [d for d, _ in fused] == ["a", "c", "b", "d"], "b and d tie; break ties by doc id"
    assert math.isclose(dict(fused)["a"], 1 / 61 + 1 / 62)
    assert [d for d, _ in lab.rrf([["a", "b"], ["b", "c"]], k=0)][0] == "b"


def test_min_max_edges():
    assert lab.min_max({"x": 2.0, "y": 4.0, "z": 3.0}) == {"x": 0.0, "y": 1.0, "z": 0.5}
    assert lab.min_max({"x": 0.4, "y": 0.4}) == {"x": 1.0, "y": 1.0}
    assert lab.min_max({}) == {}


def test_weighted_fusion_normalizes_before_weighting():
    bm25 = {"code-doc": 14.2, "policy": 7.9, "faq": 5.3}
    vec = {"policy": 0.83, "faq": 0.81, "code-doc": 0.52}
    fused = [d for d, _ in lab.weighted_fusion([vec, bm25], [0.5, 0.5])]
    assert fused[0] == "policy", "raw BM25 would dominate; normalized, the doc high in both lists wins"
    only_vec = [d for d, _ in lab.weighted_fusion([vec, bm25], [1.0, 0.0])]
    assert only_vec == ["policy", "faq", "code-doc"]


def test_hybrid_search_methods(data):
    corpus, queries, vectors = data
    bm25 = lab.BM25(lab.doc_texts(corpus))
    q = queries[0]
    qv = vectors["queries"][q["id"]]
    out = lab.hybrid_search(q["query"], qv, bm25, vectors["docs"], n=5)
    assert isinstance(out, list) and all(isinstance(d, str) for d in out)
    assert 5 <= len(out) <= 10, "fusing two top-5 lists gives between 5 and 10 unique docs"
    assert lab.hybrid_search(q["query"], qv, bm25, vectors["docs"], n=5, method="weighted")
    with pytest.raises(ValueError):
        lab.hybrid_search(q["query"], qv, bm25, vectors["docs"], method="borda")


# ---------------------------------------------------------------- reranking (fake model)


class FakeCrossEncoder:
    """Scores a pair by how many query words appear in the text; records every call."""

    def __init__(self):
        self.calls = []

    def predict(self, pairs):
        self.calls.append(list(pairs))
        return [float(len(set(q.lower().split()) & set(t.lower().split()))) for q, t in pairs]


def test_rerank_orders_by_model_scores():
    texts = {"x": "nothing here", "y": "reset password", "z": "password"}
    model = FakeCrossEncoder()
    assert lab.rerank("reset password", ["x", "z", "y"], texts, model) == ["y", "z", "x"]
    assert len(model.calls) == 1, "batch all pairs into one predict call"
    assert model.calls[0][0] == ("reset password", "nothing here"), "pairs are (query, document text)"


def test_rerank_top_n_keeps_tail_and_ties_stable():
    texts = {"a": "none", "b": "none", "c": "reset", "d": "reset password"}
    model = FakeCrossEncoder()
    assert lab.rerank("reset password", ["a", "b", "c", "d"], texts, model, top_n=2) == ["a", "b", "c", "d"], (
        "a and b tie at 0 and keep their order; c and d are outside top_n and are not reranked"
    )
    assert len(model.calls[0]) == 2


# ---------------------------------------------------------------- metrics


def test_metrics():
    assert math.isclose(lab.recall_at_k(["a", "b", "c"], {"b", "z"}, 2), 0.5)
    assert lab.recall_at_k(["a"], set(), 5) == 0.0
    assert lab.reciprocal_rank(["a", "b", "c"], {"c"}) == pytest.approx(1 / 3)
    assert lab.reciprocal_rank(["a", "b", "c"], {"c"}, k=2) == 0.0


def test_evaluate_counts_every_query():
    results = {"q1": ["a", "b"], "q2": ["c"]}
    qrels = {"q1": {"b"}, "q2": {"x"}, "q3": {"y"}}
    m = lab.evaluate(results, qrels, k=5)
    assert m["n"] == 3, "q3 has no results but is still a labeled query"
    assert m["recall"] == pytest.approx(1 / 3)
    assert m["mrr"] == pytest.approx(0.5 / 3)
    assert lab.evaluate({}, {}, k=5) == {"recall": 0.0, "mrr": 0.0, "n": 0}


# ---------------------------------------------------------------- the experiment


def test_labeled_set_is_consistent(data):
    corpus, queries, vectors = data
    ids = {d["id"] for d in corpus}
    assert all(set(q["relevant"]) <= ids for q in queries)
    assert set(vectors["docs"]) == ids and set(vectors["queries"]) == {q["id"] for q in queries}


def test_each_retriever_wins_a_different_slice(data, configs):
    _, queries, _ = data
    ident, para = qrels_for(queries, "identifier"), qrels_for(queries, "paraphrase")
    bm25_id = lab.evaluate(configs["bm25"], ident)["recall"]
    vec_id = lab.evaluate(configs["vector"], ident)["recall"]
    bm25_para = lab.evaluate(configs["bm25"], para)["recall"]
    vec_para = lab.evaluate(configs["vector"], para)["recall"]
    assert bm25_id == 1.0 and vec_id < 1.0, "exact codes: BM25 finds them all, the embedding model misses some"
    assert vec_para == 1.0 and bm25_para <= 0.5, "paraphrases: the reverse"


def test_hybrid_is_at_least_as_good_as_either_alone_on_recall(data, configs):
    _, queries, _ = data
    qrels = qrels_for(queries)
    best_single = max(lab.evaluate(configs[c], qrels)["recall"] for c in ("bm25", "vector"))
    assert lab.evaluate(configs["hybrid-weighted"], qrels)["recall"] >= best_single


def test_report_runs(data, configs):
    _, queries, _ = data
    text = lab.report(configs, queries)
    assert "hybrid-rrf" in text and "identifier" in text


# ---------------------------------------------------------------- optional: a real cross-encoder


def test_real_cross_encoder_improves_or_keeps_mrr(data):
    pytest.importorskip("sentence_transformers")
    try:
        model = lab.load_cross_encoder()
    except Exception as exc:  # no network, or the model can't be downloaded
        pytest.skip(f"could not load the cross-encoder: {exc}")
    corpus, queries, vectors = data
    configs = lab.run_all(corpus, queries, vectors, reranker=model)
    qrels = qrels_for(queries)
    before = lab.evaluate(configs["hybrid-rrf"], qrels)["mrr"]
    after = lab.evaluate(configs["hybrid-rrf+rerank"], qrels)["mrr"]
    print(f"\nMRR@5 hybrid-rrf {before:.2f} -> with rerank {after:.2f}")
    assert after >= before - 0.05, "reranking should not make MRR clearly worse on this set"
