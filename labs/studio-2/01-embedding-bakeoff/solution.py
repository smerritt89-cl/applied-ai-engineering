"""Lab 01 (Studio 2): an embedding bake-off. Reference solution.

Compare embedding models on a small labeled retrieval set with recall@k and MRR.
The embedder adapters, data loading, and CLI are provided. The metric and ranking
functions are yours (see starter.py).

    python solution.py --embedders hashing,minilm,voyage
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import re
import zlib
from dataclasses import dataclass, field
from typing import Callable, Sequence

HERE = pathlib.Path(__file__).parent
DATA = HERE / "data"

Vector = list[float]
# An embedder takes a batch of texts and their role ("query" or "document") and returns one vector per text.
Embedder = Callable[[Sequence[str], str], list[Vector]]


# ----------------------------------------------------------------- data (provided)


def load_corpus() -> list[dict]:
    """Help-center articles for a fictional bike-share company: dicts with id, title, text."""
    return json.loads((DATA / "corpus.json").read_text())


def load_queries() -> list[dict]:
    """Labeled queries: dicts with id, query, and relevant (a list of corpus ids)."""
    return json.loads((DATA / "queries.json").read_text())


def document_text(doc: dict) -> str:
    """What we embed for each article: the title, then the body."""
    return f"{doc['title']}. {doc['text']}"


# ----------------------------------------------------------------- vectors


def norm(v: Sequence[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def normalize(v: Sequence[float]) -> Vector:
    """Return v scaled to unit length. Raise ValueError for a zero vector."""
    n = norm(v)
    if n == 0:
        raise ValueError("cannot normalize a zero vector")
    return [x / n for x in v]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity. Raise ValueError if lengths differ or either vector is zero."""
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")
    na, nb = norm(a), norm(b)
    if na == 0 or nb == 0:
        raise ValueError("cosine is undefined for a zero vector")
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def rank(query_vec: Sequence[float], doc_vecs: Sequence[Sequence[float]], doc_ids: Sequence[str], k: int | None = None) -> list[str]:
    """Doc ids ordered by cosine similarity to the query, highest first.
    Ties are broken by doc id (alphabetical) so results are deterministic. Return the top k (all if k is None)."""
    scored = sorted(((cosine(query_vec, v), doc_id) for v, doc_id in zip(doc_vecs, doc_ids)), key=lambda t: (-t[0], t[1]))
    ranked = [doc_id for _, doc_id in scored]
    return ranked if k is None else ranked[:k]


# ----------------------------------------------------------------- metrics


def recall_at_k(ranked: Sequence[str], relevant: set[str] | Sequence[str], k: int) -> float:
    """Share of the relevant ids that appear in ranked[:k]. Raise ValueError if relevant is empty or k < 1."""
    relevant = set(relevant)
    if not relevant:
        raise ValueError("a labeled query needs at least one relevant id")
    if k < 1:
        raise ValueError("k must be at least 1")
    return len(set(ranked[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked: Sequence[str], relevant: set[str] | Sequence[str]) -> float:
    """1 / (1-based position of the first relevant id), or 0.0 if none appears."""
    relevant = set(relevant)
    for position, doc_id in enumerate(ranked, start=1):
        if doc_id in relevant:
            return 1.0 / position
    return 0.0


@dataclass
class QueryResult:
    query_id: str
    query: str
    relevant: list[str]
    ranked: list[str]
    recall: dict[int, float]
    rr: float


@dataclass
class Report:
    name: str
    ks: tuple[int, ...]
    results: list[QueryResult] = field(default_factory=list)

    def mean_recall(self, k: int) -> float:
        return sum(r.recall[k] for r in self.results) / len(self.results)

    def mrr(self) -> float:
        return sum(r.rr for r in self.results) / len(self.results)


def evaluate(name: str, embedder: Embedder, corpus: list[dict], queries: list[dict], ks: tuple[int, ...] = (1, 3, 5)) -> Report:
    """Embed the corpus ONCE (one call, role "document") and all queries ONCE (one call, role "query"),
    rank the whole corpus for each query, and record recall@k for every k in ks plus the reciprocal rank.
    Return a Report with one QueryResult per query, in query order. Raise ValueError if the embedder
    returns a different number of vectors than texts."""
    doc_ids = [d["id"] for d in corpus]
    doc_vecs = embedder([document_text(d) for d in corpus], "document")
    query_vecs = embedder([q["query"] for q in queries], "query")
    if len(doc_vecs) != len(corpus) or len(query_vecs) != len(queries):
        raise ValueError("embedder returned the wrong number of vectors")
    report = Report(name=name, ks=tuple(ks))
    for q, qv in zip(queries, query_vecs):
        ranked = rank(qv, doc_vecs, doc_ids)
        report.results.append(
            QueryResult(
                query_id=q["id"],
                query=q["query"],
                relevant=list(q["relevant"]),
                ranked=ranked,
                recall={k: recall_at_k(ranked, q["relevant"], k) for k in ks},
                rr=reciprocal_rank(ranked, q["relevant"]),
            )
        )
    return report


def compare_per_query(a: Report, b: Report) -> dict[str, list[str]]:
    """Compare two reports query by query on reciprocal rank.
    Return {"a_wins": [...], "b_wins": [...], "ties": [...]} of query ids, in the order of a.results.
    Raise ValueError if the reports don't cover the same queries."""
    b_by_id = {r.query_id: r for r in b.results}
    if set(b_by_id) != {r.query_id for r in a.results}:
        raise ValueError("reports cover different queries")
    out: dict[str, list[str]] = {"a_wins": [], "b_wins": [], "ties": []}
    for ra in a.results:
        rb = b_by_id[ra.query_id]
        if ra.rr > rb.rr:
            out["a_wins"].append(ra.query_id)
        elif rb.rr > ra.rr:
            out["b_wins"].append(ra.query_id)
        else:
            out["ties"].append(ra.query_id)
    return out


def failures(report: Report, k: int) -> list[QueryResult]:
    """Queries with no relevant document in the top k."""
    return [r for r in report.results if not set(r.ranked[:k]) & set(r.relevant)]


def summary_table(reports: list[Report]) -> str:
    """A small Markdown table: model, recall@k for each k, MRR."""
    ks = reports[0].ks
    head = "| model | " + " | ".join(f"recall@{k}" for k in ks) + " | MRR |"
    sep = "|---" * (len(ks) + 2) + "|"
    rows = [
        f"| {r.name} | " + " | ".join(f"{r.mean_recall(k):.3f}" for k in ks) + f" | {r.mrr():.3f} |" for r in reports
    ]
    return "\n".join([head, sep, *rows])


# ----------------------------------------------------------------- embedders (provided)

TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
STOPWORDS = frozenset(
    "a an and are as at be by can do does for from get how i if in is it me my no not of on or our so "
    "that the this to was we what when why will with you your".split()
)


def hashing_embedder(dim: int = 512) -> Embedder:
    """A keyword-style baseline that needs no model: hash each lowercase word (minus common English
    stopwords) into one of `dim` buckets, count, and normalize. It only matches shared words, so it shows what "semantic" search adds.
    zlib.crc32 is used instead of hash() because Python randomizes hash() per process."""

    def embed(texts: Sequence[str], role: str) -> list[Vector]:
        vecs = []
        for text in texts:
            v = [0.0] * dim
            for tok in TOKEN.findall(text.lower()):
                if tok in STOPWORDS:
                    continue
                v[zlib.crc32(tok.encode()) % dim] += 1.0
            vecs.append(normalize(v) if any(v) else v)
        return vecs

    return embed


def sentence_transformer_embedder(model_name: str = "sentence-transformers/all-MiniLM-L6-v2", query_prefix: str = "", document_prefix: str = "") -> Embedder:
    """A local open model via Sentence Transformers (pip install sentence-transformers).
    Some models need role prefixes, for example E5: query_prefix="query: ", document_prefix="passage: ".
    The first call downloads the weights from Hugging Face."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)

    def embed(texts: Sequence[str], role: str) -> list[Vector]:
        prefix = query_prefix if role == "query" else document_prefix
        arr = model.encode([prefix + t for t in texts], normalize_embeddings=True)
        return [list(map(float, row)) for row in arr]

    return embed


def voyage_embedder(model: str = "voyage-4-lite") -> Embedder:
    """Voyage AI via its official SDK (pip install -U voyageai). Reads VOYAGE_API_KEY.
    input_type tells Voyage whether each text is a query or a document."""
    import voyageai

    client = voyageai.Client()

    def embed(texts: Sequence[str], role: str) -> list[Vector]:
        result = client.embed(list(texts), model=model, input_type=role)
        return [list(map(float, e)) for e in result.embeddings]

    return embed


def openai_embedder(model: str = "text-embedding-3-small") -> Embedder:
    """OpenAI via its official SDK (pip install openai). Reads OPENAI_API_KEY.
    These models are symmetric: queries and documents are embedded the same way."""
    from openai import OpenAI

    client = OpenAI()

    def embed(texts: Sequence[str], role: str) -> list[Vector]:
        response = client.embeddings.create(model=model, input=list(texts))
        return [list(map(float, item.embedding)) for item in sorted(response.data, key=lambda d: d.index)]

    return embed


EMBEDDERS: dict[str, Callable[[], Embedder]] = {
    "hashing": hashing_embedder,
    "minilm": sentence_transformer_embedder,
    "e5": lambda: sentence_transformer_embedder("intfloat/e5-base-v2", "query: ", "passage: "),
    "voyage": voyage_embedder,
    "openai": openai_embedder,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Embedding bake-off on a labeled query set")
    parser.add_argument("--embedders", default="hashing", help=f"comma-separated, from: {', '.join(EMBEDDERS)}")
    parser.add_argument("--k", type=int, default=3, help="k for the failure listing")
    args = parser.parse_args()

    corpus, queries = load_corpus(), load_queries()
    reports = []
    for name in args.embedders.split(","):
        name = name.strip()
        try:
            reports.append(evaluate(name, EMBEDDERS[name](), corpus, queries))
        except ImportError as err:
            print(f"skipping {name}: {err} (see README for the pip command)")
        except Exception as err:  # missing key, network, rate limit: report and continue
            print(f"skipping {name}: {type(err).__name__}: {err}")
    if not reports:
        return
    print(summary_table(reports))
    for r in reports:
        missed = failures(r, args.k)
        print(f"\n{r.name}: {len(missed)} queries with nothing relevant in the top {args.k}")
        for m in missed:
            print(f"  {m.query_id} {m.query!r} -> {m.ranked[:args.k]} (wanted {m.relevant})")
    if len(reports) >= 2:
        a, b = reports[0], reports[1]
        cmp = compare_per_query(a, b)
        print(f"\n{a.name} vs {b.name} by reciprocal rank: {a.name} wins {cmp['a_wins']}, {b.name} wins {cmp['b_wins']}, {len(cmp['ties'])} ties")


if __name__ == "__main__":
    if (HERE.parent.parent / ".env").exists():
        try:
            from dotenv import load_dotenv

            load_dotenv(HERE.parent.parent / ".env")
        except ImportError:
            pass
    main()
