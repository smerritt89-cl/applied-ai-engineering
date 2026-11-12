"""Regenerate data/vectors.json (optional; the file is already shipped).

Needs:  pip install sentence-transformers   (downloads the model, about 90 MB, on first run)
Run:    python make_vectors.py

Documents are embedded as "title. text"; queries are embedded as typed. Vectors are
L2-normalized, so cosine similarity equals the dot product, and rounded to 5 decimals
to keep the file small.
"""
from __future__ import annotations

import json
import pathlib

from sentence_transformers import SentenceTransformer

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DATA = pathlib.Path(__file__).parent / "data"


def main() -> None:
    corpus = json.loads((DATA / "corpus.json").read_text())
    queries = json.loads((DATA / "queries.json").read_text())
    model = SentenceTransformer(MODEL)
    doc_texts = [f"{d['title']}. {d['text']}" for d in corpus]
    doc_vecs = model.encode(doc_texts, normalize_embeddings=True)
    query_vecs = model.encode([q["query"] for q in queries], normalize_embeddings=True)
    out = {
        "model": MODEL,
        "normalized": True,
        "docs": {d["id"]: [round(float(x), 5) for x in v] for d, v in zip(corpus, doc_vecs)},
        "queries": {q["id"]: [round(float(x), 5) for x in v] for q, v in zip(queries, query_vecs)},
    }
    (DATA / "vectors.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {len(out['docs'])} document and {len(out['queries'])} query vectors from {MODEL}")


if __name__ == "__main__":
    main()
