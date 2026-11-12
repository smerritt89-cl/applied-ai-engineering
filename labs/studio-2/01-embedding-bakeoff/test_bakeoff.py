"""Tests for Studio 2 lab 01. Offline tests use fixed vectors and need no key or model.

Run:  pytest studio-2/01-embedding-bakeoff -q
Optional: the local-model test runs if sentence-transformers is installed (first run downloads weights);
the Voyage test is marked live and needs VOYAGE_API_KEY (and, by the labs convention, ANTHROPIC_API_KEY).
"""
from __future__ import annotations

import math
import os

import pytest

import starter as lab

# ---------------------------------------------------------------- fixtures: a tiny world with fixed vectors

CORPUS = [
    {"id": "refunds", "title": "Refunds", "text": "money back"},
    {"id": "outage", "title": "Outage", "text": "site down"},
    {"id": "password", "title": "Password", "text": "reset login"},
]
QUERIES = [
    {"id": "q1", "query": "charged twice", "relevant": ["refunds"]},
    {"id": "q2", "query": "cannot log in", "relevant": ["password"]},
    {"id": "q3", "query": "is it broken", "relevant": ["outage", "password"]},
]
# Vectors chosen so the rankings are known in advance:
#   q1 -> refunds, outage, password   (relevant at rank 1)
#   q2 -> outage, password, refunds   (relevant at rank 2)
#   q3 -> refunds, outage, password   (first relevant at rank 2; both relevant by rank 3)
DOC_VECS = {
    "Refunds. money back": [1.0, 0.0, 0.0],
    "Outage. site down": [0.0, 1.0, 0.0],
    "Password. reset login": [0.0, 0.0, 1.0],
}
QUERY_VECS = {
    "charged twice": [0.9, 0.3, 0.1],
    "cannot log in": [0.1, 0.8, 0.6],
    "is it broken": [0.7, 0.6, 0.2],
}


class FakeEmbedder:
    """Returns fixed vectors and records every call, so tests can check batching and roles."""

    def __init__(self):
        self.calls: list[tuple[str, int]] = []

    def __call__(self, texts, role):
        self.calls.append((role, len(texts)))
        table = DOC_VECS if role == "document" else QUERY_VECS
        return [list(table[t]) for t in texts]


# ---------------------------------------------------------------- vectors


def test_normalize_gives_unit_length():
    v = lab.normalize([3.0, 4.0])
    assert v == pytest.approx([0.6, 0.8])
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0)


def test_normalize_rejects_zero_vector():
    with pytest.raises(ValueError):
        lab.normalize([0.0, 0.0, 0.0])


def test_cosine_basics():
    assert lab.cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert lab.cosine([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0), "cosine ignores length"
    assert lab.cosine([1, 0], [-1, 0]) == pytest.approx(-1.0)


def test_cosine_rejects_bad_inputs():
    with pytest.raises(ValueError):
        lab.cosine([1, 2], [1, 2, 3])
    with pytest.raises(ValueError):
        lab.cosine([0, 0], [1, 1])


def test_rank_orders_by_cosine_not_dot_product():
    # "long" has the bigger dot product with the query but points the wrong way.
    ids = ["aligned", "long"]
    vecs = [[1.0, 0.1], [3.0, 3.0]]
    assert lab.rank([1.0, 0.0], vecs, ids) == ["aligned", "long"]


def test_rank_breaks_ties_by_id_and_truncates():
    ids = ["b", "a", "c"]
    vecs = [[2.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    assert lab.rank([1.0, 0.0], vecs, ids) == ["a", "b", "c"], "equal cosines are ordered by id"
    assert lab.rank([1.0, 0.0], vecs, ids, k=2) == ["a", "b"]


# ---------------------------------------------------------------- metrics


def test_recall_at_k():
    assert lab.recall_at_k(["a", "b", "c"], {"b", "z"}, 2) == 0.5
    assert lab.recall_at_k(["a", "b", "c"], ["c"], 2) == 0.0
    assert lab.recall_at_k(["a"], {"a"}, 10) == 1.0, "k beyond the list length is fine"


def test_recall_rejects_empty_labels_and_bad_k():
    with pytest.raises(ValueError):
        lab.recall_at_k(["a"], set(), 3)
    with pytest.raises(ValueError):
        lab.recall_at_k(["a"], {"a"}, 0)


def test_reciprocal_rank():
    assert lab.reciprocal_rank(["x", "y", "a"], {"a"}) == pytest.approx(1 / 3)
    assert lab.reciprocal_rank(["a", "b"], {"b", "a"}) == 1.0, "only the first relevant hit counts"
    assert lab.reciprocal_rank(["x", "y"], {"a"}) == 0.0


# ---------------------------------------------------------------- evaluation


def test_evaluate_batches_once_per_role():
    fake = FakeEmbedder()
    lab.evaluate("fake", fake, CORPUS, QUERIES)
    assert sorted(fake.calls) == [("document", 3), ("query", 3)], (
        "embed the corpus once with role 'document' and the queries once with role 'query'; "
        f"got calls {fake.calls}"
    )


def test_evaluate_metrics_with_fixed_vectors():
    report = lab.evaluate("fake", FakeEmbedder(), CORPUS, QUERIES, ks=(1, 3))
    assert [r.query_id for r in report.results] == ["q1", "q2", "q3"]
    by_id = {r.query_id: r for r in report.results}
    assert by_id["q1"].ranked == ["refunds", "outage", "password"]
    assert by_id["q2"].ranked == ["outage", "password", "refunds"]
    assert by_id["q2"].rr == 0.5
    assert by_id["q3"].recall == {1: 0.0, 3: 1.0}
    assert report.mean_recall(1) == pytest.approx(1 / 3)
    assert report.mrr() == pytest.approx((1 + 0.5 + 0.5) / 3)


def test_evaluate_rejects_wrong_vector_count():
    def broken(texts, role):
        return [[1.0, 0.0, 0.0]]  # always one vector, whatever the batch size

    with pytest.raises(ValueError):
        lab.evaluate("broken", broken, CORPUS, QUERIES)


def _report(name, rrs):
    rep = lab.Report(name=name, ks=(1,))
    for qid, rr in rrs.items():
        rep.results.append(lab.QueryResult(qid, qid, ["d"], ["d"], {1: 1.0 if rr == 1 else 0.0}, rr))
    return rep


def test_compare_per_query():
    a = _report("a", {"q1": 1.0, "q2": 0.5, "q3": 0.0})
    b = _report("b", {"q1": 1.0, "q2": 1.0, "q3": 0.25})
    assert lab.compare_per_query(a, b) == {"a_wins": [], "b_wins": ["q2", "q3"], "ties": ["q1"]}


def test_compare_requires_same_queries():
    with pytest.raises(ValueError):
        lab.compare_per_query(_report("a", {"q1": 1.0}), _report("b", {"q2": 1.0}))


def test_failures_lists_queries_with_nothing_relevant_in_top_k():
    report = lab.evaluate("fake", FakeEmbedder(), CORPUS, QUERIES, ks=(1, 3))
    assert [r.query_id for r in lab.failures(report, 1)] == ["q2", "q3"]
    assert lab.failures(report, 3) == []


# ---------------------------------------------------------------- the real data set


def test_labels_point_at_real_documents():
    ids = {d["id"] for d in lab.load_corpus()}
    queries = lab.load_queries()
    assert len(queries) >= 12
    for q in queries:
        assert q["relevant"], f"{q['id']} has no relevant documents"
        assert set(q["relevant"]) <= ids, f"{q['id']} points at unknown ids {set(q['relevant']) - ids}"


def test_keyword_baseline_finds_exact_codes_but_misses_paraphrases():
    report = lab.evaluate("hashing", lab.hashing_embedder(), lab.load_corpus(), lab.load_queries())
    by_id = {r.query_id: r for r in report.results}
    assert by_id["q03"].ranked[0] == "error-e417", "an exact error code is easy for word matching"
    missed = {r.query_id for r in lab.failures(report, 3)}
    assert "q14" in missed, "a Spanish query shares no words with the English article"
    assert 0.3 < report.mrr() < 0.9, "the baseline should be useful but clearly imperfect"


# ---------------------------------------------------------------- optional: real models


def test_local_sentence_transformer_model():
    pytest.importorskip("sentence_transformers")
    embed = lab.sentence_transformer_embedder()
    vec = embed(["Unlocking a bike"], "document")[0]
    assert math.isclose(math.sqrt(sum(x * x for x in vec)), 1.0, rel_tol=1e-3), "the adapter normalizes vectors"
    report = lab.evaluate("minilm", embed, lab.load_corpus(), lab.load_queries())
    print("\n" + lab.summary_table([report]))
    assert report.mean_recall(5) >= 0.5, "a general-purpose model should find most answers in the top 5"


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("VOYAGE_API_KEY"), reason="set VOYAGE_API_KEY to run the Voyage test")
def test_live_voyage_embeddings_are_unit_length_and_useful():
    pytest.importorskip("voyageai")
    embed = lab.voyage_embedder()
    vec = embed(["Unlocking a bike"], "document")[0]
    assert math.isclose(math.sqrt(sum(x * x for x in vec)), 1.0, rel_tol=1e-3), "Voyage documents unit-length vectors"
    report = lab.evaluate("voyage", embed, lab.load_corpus(), lab.load_queries())
    baseline = lab.evaluate("hashing", lab.hashing_embedder(), lab.load_corpus(), lab.load_queries())
    print("\n" + lab.summary_table([baseline, report]))
    assert report.mean_recall(5) >= 0.6
