# Lab 03: Hybrid retrieval, measured

**Goes with:** Studio 2, week 3 (lessons 7 to 9). **Time:** about 75 minutes. **API key:** not needed.

## Goal

Build a small hybrid retriever and find out, with numbers, what each piece is worth:

1. **BM25** over an inverted index you build yourself.
2. **Vector search** with precomputed embeddings (brute-force cosine; the corpus is small).
3. **Fusion** two ways: reciprocal rank fusion (RRF) and min-max normalized weighted scores.
4. **Reranking** with a cross-encoder (optional; tested offline with a fake model).
5. **Evaluation**: recall@5 and MRR@5 per configuration, overall and per query type, on a labeled query set.

## The data

- `data/corpus.json`: 42 short, fictional internal knowledge-base articles (IT, HR, finance, security, facilities).
  Several look alike on purpose: VPN-719, VPN-722, and VPN-801 are different errors; forms IT-12, IT-14, and IT-19 do
  different things.
- `data/queries.json`: 20 labeled queries, each tagged `identifier` (codes, form numbers, names), `paraphrase`
  (no shared vocabulary with the answer), or `mixed`, with the ids of the articles that answer it.
- `data/vectors.json`: embeddings for every article and query from the open model
  `sentence-transformers/all-MiniLM-L6-v2`, L2-normalized and rounded to 5 decimals. `make_vectors.py` shows exactly
  how they were made; you don't need to run it. Because query vectors are precomputed, the offline pipeline can only
  answer the 20 labeled queries. To try new queries, install sentence-transformers and embed them with the same model.

## Steps

Work in `starter.py`; the tests import from it. Only the standard library is needed.

1. **BM25.** Fill in `BM25.__init__`, `idf`, `score`, and `search`. The tokenizer is given; read it first and notice
   that it keeps hyphenated identifiers such as `vpn-719` whole.
2. **Vectors.** Write `cosine` and `vector_search`.
3. **Fusion.** Write `rrf`, `min_max`, `weighted_fusion`, and `hybrid_search`.
4. **Reranking.** Write `rerank`. The tests use a fake model with a `predict(pairs)` method, the same interface as
   `sentence_transformers.CrossEncoder`.
5. **Metrics.** Write `recall_at_k`, `reciprocal_rank`, and `evaluate`.
6. Run the tests until they pass, then print the comparison table:

   ```bash
   cd labs && source .venv/bin/activate
   pytest studio-2/03-hybrid-retrieval -q
   python studio-2/03-hybrid-retrieval/starter.py
   ```

7. **Optional: a real reranker.** Install the extra package (it pulls in PyTorch, a large download) and run with
   `--rerank`. The first run downloads `cross-encoder/ms-marco-MiniLM-L6-v2` (about 90 MB) from Hugging Face.

   ```bash
   pip install sentence-transformers
   python studio-2/03-hybrid-retrieval/starter.py --rerank
   pytest studio-2/03-hybrid-retrieval -q -k real -s
   ```

   Without the package, that test is skipped.

## Expected cost

Nothing. Every test runs offline. The optional reranker runs locally on a CPU in a few seconds for this corpus.

## What to notice

When we ran the reference solution, the table looked like this (recall@5 / MRR@5):

| config | all (20) | identifier (7) | mixed (5) | paraphrase (8) |
|---|---|---|---|---|
| bm25 | 0.80 / 0.71 | 1.00 / 1.00 | 1.00 / 0.90 | 0.50 / 0.34 |
| vector | 0.95 / 0.93 | 0.86 / 0.79 | 1.00 / 1.00 | 1.00 / 1.00 |
| hybrid-rrf | 0.95 / 0.86 | 1.00 / 0.90 | 1.00 / 1.00 | 0.88 / 0.73 |
| hybrid-weighted | 1.00 / 0.92 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 0.79 |
| hybrid-rrf + rerank | 1.00 / 0.96 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 0.90 |

- **Each retriever wins a slice.** BM25 finds every identifier query and half the paraphrases. The embedding model
  finds every paraphrase and misses an identifier: for "where do I find form IT-12" it ranks four other form articles
  (IT-19, HR-6, HR-11, HR-9) and a purchase-order article above the IT-12 one. The per-type breakdown shows
  this; the "all" column hides it. Always split by query type.
- **Hybrid is not automatically better.** Here RRF lost paraphrase recall compared with vectors alone. Look at why:
  for "suspicious message asking me to wire money", BM25's top five are all unrelated articles that share only
  the word "to" (and, for one, "message"), and RRF gives that list as much say as the vector list. Normalized weighted fusion did better on this set. Try a stop-word list
  in `tokenize`, or `alpha` values from 0.3 to 0.8, and re-run. Which change helps the paraphrase slice without hurting
  identifiers?
- **Reranking fixed the order, not the recall problem.** The cross-encoder can only reorder candidates it receives.
  It lifted MRR because the right article was already among the fused candidates.
- **These are 20 queries.** One query moves a slice's recall by 0.12 to 0.20. Treat differences of that size as
  hypotheses for a bigger labeled set, not as conclusions. In a real project you'd grow the set from real user queries
  (lesson 9) before choosing a configuration, and you'd keep some queries aside that you didn't look at while tuning.
- **Model choice is part of the experiment.** `all-MiniLM-L6-v2` is small and old by current standards. A stronger
  embedding model might close the identifier gap or might not; you now have the harness to find out instead of
  guessing.
