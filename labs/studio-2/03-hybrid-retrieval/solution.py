"""Lab 03 (Studio 2): hybrid retrieval, measured. Reference solution.

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
        self.k1 = k1
        self.b = b
        self.postings: dict[str, dict[str, int]] = {}
        self.lengths: dict[str, int] = {}
        for doc_id, text in docs.items():
            tokens = tokenize(text)
            self.lengths[doc_id] = len(tokens)
            for term, tf in Counter(tokens).items():
                self.postings.setdefault(term, {})[doc_id] = tf
        self.n_docs = len(docs)
        self.avgdl = sum(self.lengths.values()) / self.n_docs if self.n_docs else 0.0

    def idf(self, term: str) -> float:
        n = len(self.postings.get(term, {}))
        return math.log(1 + (self.n_docs - n + 0.5) / (n + 0.5))

    def score(self, query: str, doc_id: str) -> float:
        dl = self.lengths[doc_id]
        norm = self.k1 * (1 - self.b + self.b * dl / self.avgdl)
        total = 0.0
        for term in tokenize(query):
            tf = self.postings.get(term, {}).get(doc_id, 0)
            if tf:
                total += self.idf(term) * tf * (self.k1 + 1) / (tf + norm)
        return total

    def search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        candidates: set[str] = set()
        for term in tokenize(query):
            candidates.update(self.postings.get(term, {}))
        scored = [(d, self.score(query, d)) for d in candidates]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:k]


# ---------------------------------------------------------------- vectors


def cosine(u: list[float], v: list[float]) -> float:
    dot = sum(a * b for a, b in zip(u, v))
    nu = math.sqrt(sum(a * a for a in u))
    nv = math.sqrt(sum(b * b for b in v))
    if nu == 0 or nv == 0:
        return 0.0
    return dot / (nu * nv)


def vector_search(query_vec: list[float], doc_vecs: dict[str, list[float]], k: int = 10) -> list[tuple[str, float]]:
    scored = [(d, cosine(query_vec, v)) for d, v in doc_vecs.items()]
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored[:k]


# ---------------------------------------------------------------- fusion


def rrf(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


def min_max(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    lo, hi = min(scores.values()), max(scores.values())
    if hi == lo:
        return {d: 1.0 for d in scores}
    return {d: (s - lo) / (hi - lo) for d, s in scores.items()}


def weighted_fusion(score_dicts: list[dict[str, float]], weights: list[float]) -> list[tuple[str, float]]:
    total: dict[str, float] = {}
    for scores, weight in zip(score_dicts, weights):
        for d, s in min_max(scores).items():
            total[d] = total.get(d, 0.0) + weight * s
    return sorted(total.items(), key=lambda pair: (-pair[1], pair[0]))


def hybrid_search(
    query: str,
    query_vec: list[float],
    bm25: BM25,
    doc_vecs: dict[str, list[float]],
    n: int = 20,
    method: str = "rrf",
    alpha: float = 0.5,
) -> list[str]:
    keyword = bm25.search(query, k=n)
    dense = vector_search(query_vec, doc_vecs, k=n)
    if method == "rrf":
        fused = rrf([[d for d, _ in keyword], [d for d, _ in dense]])
    elif method == "weighted":
        fused = weighted_fusion([dict(dense), dict(keyword)], [alpha, 1 - alpha])
    else:
        raise ValueError(f"unknown fusion method: {method!r}")
    return [d for d, _ in fused]


# ---------------------------------------------------------------- reranking


def rerank(query: str, candidates: list[str], texts: dict[str, str], model, top_n: int | None = None) -> list[str]:
    """Reorder candidates by model.predict([(query, text), ...]) scores, highest first.
    Candidates beyond top_n (if given) keep their original order after the reranked ones."""
    head = candidates if top_n is None else candidates[:top_n]
    tail = [] if top_n is None else candidates[top_n:]
    if not head:
        return list(candidates)
    scores = model.predict([(query, texts[d]) for d in head])
    order = sorted(range(len(head)), key=lambda i: (-float(scores[i]), i))
    return [head[i] for i in order] + tail


# ---------------------------------------------------------------- metrics


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return sum(1 for d in ranked[:k] if d in relevant) / len(relevant)


def reciprocal_rank(ranked: list[str], relevant: set[str], k: int | None = None) -> float:
    for i, d in enumerate(ranked[:k] if k else ranked, start=1):
        if d in relevant:
            return 1.0 / i
    return 0.0


def evaluate(results: dict[str, list[str]], qrels: dict[str, set[str]], k: int = 5) -> dict[str, float]:
    """Mean recall@k and MRR@k over every query in qrels. A query missing from results counts as 0."""
    if not qrels:
        return {"recall": 0.0, "mrr": 0.0, "n": 0}
    recall = sum(recall_at_k(results.get(q, []), rel, k) for q, rel in qrels.items())
    mrr = sum(reciprocal_rank(results.get(q, []), rel, k) for q, rel in qrels.items())
    return {"recall": recall / len(qrels), "mrr": mrr / len(qrels), "n": len(qrels)}


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
