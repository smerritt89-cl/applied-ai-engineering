"""Lab 03 (Studio 2): hybrid retrieval, measured (your file: fill in the TODOs).

Pipeline:
    query -> BM25 top N  \
                          -> fusion (RRF or normalized weighted sum) -> optional cross-encoder rerank
    query -> vector top N /
    then recall@k and MRR per configuration and per query type, on a labeled query set.

Everything runs offline with the standard library: document and query vectors were
precomputed with an open embedding model (see make_vectors.py) and ship in data/vectors.json.
"""
from __future__ import annotations

import json
import math
import pathlib
import re
from collections import Counter

DATA = pathlib.Path(__file__).parent / "data"


# ---------------------------------------------------------------- data


def load_data(data_dir: pathlib.Path = DATA) -> tuple[list[dict], list[dict], dict]:
    """Return (corpus, queries, vectors) from the JSON files in data_dir."""
    corpus = json.loads((data_dir / "corpus.json").read_text())
    queries = json.loads((data_dir / "queries.json").read_text())
    vectors = json.loads((data_dir / "vectors.json").read_text())
    return corpus, queries, vectors


def doc_texts(corpus: list[dict]) -> dict[str, str]:
    """Map doc id to the text we index: title, then body."""
    return {d["id"]: f"{d['title']}. {d['text']}" for d in corpus}


# ---------------------------------------------------------------- BM25


def tokenize(text: str) -> list[str]:
    """Lowercase; keep hyphenated identifiers such as vpn-719 or po-2026-01182 as single tokens."""
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower())


class BM25:
    """Okapi BM25 over an in-memory inverted index (Lucene's always-positive idf)."""

    def __init__(self, docs: dict[str, str], k1: float = 1.2, b: float = 0.75):
        """Build the inverted index from {doc_id: text}.

        TODO: set self.k1, self.b, and
          self.postings  {term: {doc_id: term frequency}}   (use tokenize)
          self.lengths   {doc_id: number of tokens}
          self.n_docs    number of documents
          self.avgdl     mean document length in tokens (0.0 for an empty corpus)
        """
        raise NotImplementedError("TODO")

    def idf(self, term: str) -> float:
        """TODO: Lucene's form, log(1 + (N - n + 0.5) / (n + 0.5)), n = number of docs containing term."""
        raise NotImplementedError("TODO")

    def score(self, query: str, doc_id: str) -> float:
        """TODO: sum over query tokens of idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl)).
        Tokens that don't occur in the document contribute nothing."""
        raise NotImplementedError("TODO")

    def search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        """TODO: score only documents containing at least one query token.
        Return up to k (doc_id, score) pairs, highest first, ties broken by doc_id."""
        raise NotImplementedError("TODO")


# ---------------------------------------------------------------- vectors


def cosine(u: list[float], v: list[float]) -> float:
    """TODO: cosine similarity; return 0.0 if either vector has zero length."""
    raise NotImplementedError("TODO")


def vector_search(query_vec: list[float], doc_vecs: dict[str, list[float]], k: int = 10) -> list[tuple[str, float]]:
    """TODO: brute-force nearest neighbors. Return the top k (doc_id, cosine), highest first, ties by doc_id."""
    raise NotImplementedError("TODO")


# ---------------------------------------------------------------- fusion


def rrf(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """TODO: reciprocal rank fusion (Cormack, Clarke, Buettcher 2009).
    rankings: lists of doc ids, best first. score(d) = sum over lists containing d of 1 / (k + rank), rank from 1.
    Return (doc_id, score) pairs, highest first, ties by doc_id."""
    raise NotImplementedError("TODO")


def min_max(scores: dict[str, float]) -> dict[str, float]:
    """TODO: map scores to [0, 1] (best 1, worst 0). Empty -> {}. All equal -> every doc 1.0."""
    raise NotImplementedError("TODO")


def weighted_fusion(score_dicts: list[dict[str, float]], weights: list[float]) -> list[tuple[str, float]]:
    """TODO: min-max normalize each retriever's scores, then sum weight * normalized score per doc
    (a doc missing from a retriever gets 0 from it). Return (doc_id, score) pairs, highest first, ties by doc_id."""
    raise NotImplementedError("TODO")


def hybrid_search(
    query: str,
    query_vec: list[float],
    bm25: BM25,
    doc_vecs: dict[str, list[float]],
    n: int = 20,
    method: str = "rrf",
    alpha: float = 0.5,
) -> list[str]:
    """TODO: retrieve the top n from BM25 and from vectors, then fuse.
    method="rrf":      rrf([bm25 ids, vector ids])
    method="weighted": weighted_fusion([vector scores, bm25 scores], [alpha, 1 - alpha])
    anything else:     raise ValueError
    Return the fused doc ids only, best first."""
    raise NotImplementedError("TODO")


# ---------------------------------------------------------------- reranking


def rerank(query: str, candidates: list[str], texts: dict[str, str], model, top_n: int | None = None) -> list[str]:
    """Reorder candidates by model.predict([(query, text), ...]) scores, highest first.
    Candidates beyond top_n (if given) keep their original order after the reranked ones.

    TODO: call model.predict ONCE with (query, texts[doc_id]) pairs for the head of the list;
    break score ties by original position. Return a new list of doc ids."""
    raise NotImplementedError("TODO")


# ---------------------------------------------------------------- metrics


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """TODO: |relevant in top k| / |relevant|; 0.0 if relevant is empty."""
    raise NotImplementedError("TODO")


def reciprocal_rank(ranked: list[str], relevant: set[str], k: int | None = None) -> float:
    """TODO: 1 / rank of the first relevant doc within the first k (all if k is None); 0.0 if none."""
    raise NotImplementedError("TODO")


def evaluate(results: dict[str, list[str]], qrels: dict[str, set[str]], k: int = 5) -> dict[str, float]:
    """Mean recall@k and MRR@k over every query in qrels. A query missing from results counts as 0.

    TODO: return {"recall": ..., "mrr": ..., "n": number of queries}; for empty qrels return zeros and n = 0."""
    raise NotImplementedError("TODO")


# ---------------------------------------------------------------- experiment


def run_all(corpus, queries, vectors, n: int = 20, reranker=None) -> dict[str, dict[str, list[str]]]:
    """Return {config_name: {query_id: ranked doc ids}} for each retrieval configuration."""
    texts = doc_texts(corpus)
    bm25 = BM25(texts)
    doc_vecs = vectors["docs"]
    configs: dict[str, dict[str, list[str]]] = {"bm25": {}, "vector": {}, "hybrid-rrf": {}, "hybrid-weighted": {}}
    if reranker is not None:
        configs["hybrid-rrf+rerank"] = {}
    for q in queries:
        qv = vectors["queries"][q["id"]]
        configs["bm25"][q["id"]] = [d for d, _ in bm25.search(q["query"], k=n)]
        configs["vector"][q["id"]] = [d for d, _ in vector_search(qv, doc_vecs, k=n)]
        fused = hybrid_search(q["query"], qv, bm25, doc_vecs, n=n, method="rrf")
        configs["hybrid-rrf"][q["id"]] = fused
        configs["hybrid-weighted"][q["id"]] = hybrid_search(q["query"], qv, bm25, doc_vecs, n=n, method="weighted")
        if reranker is not None:
            configs["hybrid-rrf+rerank"][q["id"]] = rerank(q["query"], fused, texts, reranker, top_n=n)
    return configs


def report(configs, queries, k: int = 5) -> str:
    types = sorted({q["type"] for q in queries})
    groups = {"all": queries, **{t: [q for q in queries if q["type"] == t] for t in types}}
    header = f"{'config':<20}" + "".join(f"{g + f' (n={len(qs)})':>26}" for g, qs in groups.items())
    lines = [f"recall@{k} / MRR@{k}", header]
    for name, results in configs.items():
        row = f"{name:<20}"
        for qs in groups.values():
            m = evaluate(results, {q["id"]: set(q["relevant"]) for q in qs}, k)
            row += f"{m['recall']:>17.2f} / {m['mrr']:.2f}"
        lines.append(row)
    return "\n".join(lines)


def load_cross_encoder(name: str = "cross-encoder/ms-marco-MiniLM-L6-v2"):
    """Optional: needs `pip install sentence-transformers` and downloads the model on first use."""
    from sentence_transformers import CrossEncoder

    return CrossEncoder(name)


if __name__ == "__main__":
    import sys

    corpus, queries, vectors = load_data()
    reranker = load_cross_encoder() if "--rerank" in sys.argv else None
    print(f"Embeddings: {vectors['model']}  |  {len(corpus)} docs, {len(queries)} labeled queries\n")
    print(report(run_all(corpus, queries, vectors, reranker=reranker), queries))
