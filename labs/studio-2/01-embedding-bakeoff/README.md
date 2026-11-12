# Lab 01 (Studio 2): an embedding bake-off

**Goes with:** Studio 2, week 1 (lessons 1 to 3, especially lesson 2). **Time:** about 60 minutes.

## Goal

Decide between embedding models with evidence instead of a leaderboard. You will:

1. Implement cosine similarity, ranking, **recall@k**, and **MRR**, tested offline with fixed vectors.
2. Write an `evaluate` function that embeds a corpus once, embeds every query once, ranks, and scores.
3. Run it on a small labeled set (20 help-center articles for a fictional bike-share company, 16 queries with
   relevance labels) using up to three embedders:
   - `hashing`: a keyword-style baseline built in (no model, no key). It only matches shared words.
   - `minilm`: a local open model, `sentence-transformers/all-MiniLM-L6-v2`, via Sentence Transformers.
   - `voyage` or `openai`: a provider API model via its official SDK, if you have a key.
4. Read the per-query failures and the head-to-head comparison, and write down which model you'd pick and why.

The queries deliberately include paraphrases with no shared words ("how do I stop paying for my subscription"),
an exact error code ("E-417"), a question in Spanish, and two queries with more than one relevant article.

## Setup

The offline tests need only the shared lab environment (`labs/requirements.txt`). The optional embedders need extra
packages, which are not in the shared requirements:

```bash
cd labs && source .venv/bin/activate
pip install sentence-transformers   # local models; pulls in PyTorch (a large download)
pip install -U voyageai             # Voyage AI SDK (0.3.7 or later for keys created in MongoDB Atlas)
pip install openai                  # optional alternative provider
```

Keys go in `labs/.env`: `VOYAGE_API_KEY=...` (create one under **AI Model APIs** in MongoDB Atlas, as Anthropic's
embeddings guide describes) or `OPENAI_API_KEY=...`.

## Steps

Work in `starter.py`. The tests import from it.

1. **Vectors.** Implement `normalize`, `cosine`, and `rank`. `rank` sorts by cosine (highest first) and breaks ties
   by document id, so results are reproducible.
2. **Metrics.** Implement `recall_at_k` (share of the relevant ids found in the top k) and `reciprocal_rank`
   (1 over the position of the first relevant id, or 0).
3. **Evaluation.** Implement `evaluate`. Embed the corpus in **one** call with role `"document"` and the queries in
   **one** call with role `"query"`; the fake embedder in the tests checks both. Roles matter for asymmetric models
   (Voyage's `input_type`, E5's `query: ` and `passage: ` prefixes) and are ignored by symmetric ones.
4. **Comparison.** Implement `compare_per_query` and `failures`.
5. Run the offline tests until they pass:

   ```bash
   pytest studio-2/01-embedding-bakeoff -q
   ```

6. Run the bake-off. Start with the baseline, then add what you installed:

   ```bash
   python studio-2/01-embedding-bakeoff/starter.py --embedders hashing
   python studio-2/01-embedding-bakeoff/starter.py --embedders hashing,minilm
   python studio-2/01-embedding-bakeoff/starter.py --embedders minilm,voyage
   ```

   The script prints recall@1, @3, @5 and MRR per embedder, the queries each one misses in the top 3, and a
   per-query comparison of the first two. Other options: `e5` (`intfloat/e5-base-v2`, with its required prefixes) and
   `openai` (`text-embedding-3-small`). Add your own by writing a function with the same shape as the adapters.

7. Optional tests against real models:

   ```bash
   pytest studio-2/01-embedding-bakeoff -q -s                 # includes the local model if installed
   pytest studio-2/01-embedding-bakeoff -q -s -m live         # the Voyage test
   ```

   The Voyage test is marked `live` and also needs `VOYAGE_API_KEY`. The shared `labs/conftest.py` skips every live
   test unless `ANTHROPIC_API_KEY` is set as well, so set both (or run the script in step 6, which has no such gate).

## Expected cost

Offline tests and the `hashing` and local runs: free (the first local run downloads model weights, about 90 MB for
MiniLM). The provider runs embed about 1,500 tokens of articles and queries per run, a tiny fraction of a cent at the
per-million-token prices on the providers' pricing pages. Check the current pricing
pages before relying on that.

## What to notice

- **Where keywords win and lose.** The `hashing` baseline nails "E-417" and fails the Spanish query and the
  paraphrases. Note which of those each embedding model fixes, and check whether any model now ranks the E-416 article
  above E-417 for the error-code query. That pattern is the argument for hybrid search in week 3.
- **Averages versus queries.** With 16 queries, one query moves recall@k by over 6 points. Read `compare_per_query`
  before you believe a difference in means, and ask whether the queries a model wins are the ones your users ask.
- **Multilingual needs.** `all-MiniLM-L6-v2` was trained for English. If Spanish matters to your users, it belongs in
  your test set and probably in your model choice (try a multilingual E5 model).
- **Roles and prefixes.** Run `e5` with its prefixes, then edit the adapter to drop them and run again. Nothing
  errors; only the numbers change. That is why the roles are worth testing, not assuming.
- **Check the vectors themselves.** The live test asserts that Voyage vectors have unit length, as its docs state. If
  you add a provider, assert what its docs promise (length, dimension) the same way.
- **This set is too small to decide on its own.** It teaches the method. For a real decision, build 30 to 100
  queries from your own users, label them without looking at any one model's results, and keep the set as a
  regression test for chunking and reranking changes later in the studio.
