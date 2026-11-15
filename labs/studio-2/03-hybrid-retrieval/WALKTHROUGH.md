# Walkthrough: hybrid retrieval, measured

## What this code does

`solution.py` builds a small search engine three ways and then grades each one. It indexes 42 fictional knowledge-base articles with **BM25** (keyword search), searches the same articles with **precomputed embeddings** (vector search), and combines the two result lists with **fusion**, either reciprocal rank fusion (RRF) or a normalized weighted sum. An optional **cross-encoder** reranks the fused list.

Then it scores every configuration on 20 labeled queries with **recall@5** (did the right article make the top five?) and **MRR@5** (how high up was the first right article?), overall and per query type. That per-type split is the point of the lab: keyword search wins on codes like `VPN-719`, vector search wins on paraphrases, and an "all queries" average hides both facts.

Everything uses only the Python standard library. The embeddings were made ahead of time and ship in `data/vectors.json`, so nothing downloads and nothing costs money unless you opt into the real reranker.

## How to read this lab

Open `work.py` beside this page. It starts as an exact copy of `solution.py` (made by `python lab.py review`), so the line numbers below match it until you edit it. Run the tests from VS Code's **Testing** panel (the flask icon): expand `studio-2 > 03-hybrid-retrieval` and press the run arrow. They should all pass. To see the comparison table, run `python studio-2/03-hybrid-retrieval/work.py` from the `labs` folder.

Read the sections in order. The file is laid out like the pipeline: data, BM25, vectors, fusion, reranking, metrics, experiment.

## Module header and imports (lines 1 to 20)

```python
from __future__ import annotations

import json
import math
import pathlib
import re
from collections import Counter

DATA = pathlib.Path(__file__).parent / "data"
```

The docstring at the top draws the pipeline as a small diagram. That is worth doing in real code: a reviewer can check each function against the picture.

`from __future__ import annotations` lets the file use modern **type hints** such as `list[dict]` and `int | None` without worrying about the Python version. Type hints are the `: str` and `-> float` labels on function arguments and return values. Python does not enforce them at run time; they are documentation that editors and tools can check.

`pathlib.Path(__file__).parent / "data"` builds the path to the data folder relative to this file, not to wherever you happen to run Python from. The `/` operator on a `Path` joins path pieces. This is why `python studio-2/03-hybrid-retrieval/work.py` works from the `labs` folder. AI-written code often uses a bare `"data/corpus.json"`, which only works from one directory.

The import list is short and all standard library. When you review an AI's version of this lab, an unexpected import (NumPy, scikit-learn, a vector database client) is a sign it solved a different problem than the one asked.

## `load_data` and `doc_texts` (lines 26 to 36)

```python
def doc_texts(corpus: list[dict]) -> dict[str, str]:
    return {d["id"]: f"{d['title']}. {d['text']}" for d in corpus}
```

`load_data` reads the three JSON files and returns them as a **tuple**, which the caller unpacks: `corpus, queries, vectors = load_data()`. The `data_dir` argument has a default, so tests and scripts can call it with no arguments, while a test could still point it at a different folder.

`doc_texts` is a **dict comprehension**: it builds a dictionary from doc id to the text that gets indexed. The value is an **f-string** (a string with `{...}` slots filled in from variables) that puts the title first, then the body. Including the title matters: an article titled "Error VPN-719" should match the query "VPN-719" even if the body phrased it differently.

## `tokenize` (lines 42 to 44)

```python
return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower())
```

This one line decides what counts as a word, and every BM25 result depends on it. `re.findall` returns every match of a **regular expression** (a pattern language for text). Read the pattern in two parts:

- `[a-z0-9]+` is one or more letters or digits.
- `(?:-[a-z0-9]+)*` is zero or more repeats of "a hyphen followed by more letters or digits". The `(?: ... )` groups without capturing.

So `"Error VPN-719, see PO-2026-01182."` becomes `["error", "vpn-719", "see", "po-2026-01182"]`. Lowercasing first means "VPN" and "vpn" match. Punctuation disappears.

**Why it is built this way.** A simpler tokenizer that splits on anything that isn't a letter or digit would turn `vpn-719` into `vpn` and `719`. The identifier is then no longer one rare term; it is a common word ("vpn", in many articles) plus a number that could appear anywhere. Keeping it whole means one token carries the whole meaning and gets a high idf. If an AI "simplifies" this regex, the unit tests below catch it (see review question 1), but note that this small labeled set does not: the right article still contains both pieces, so the identifier slice happens to stay at 1.00. A bigger corpus with more look-alike codes would expose it.

## `BM25.__init__`: building the inverted index (lines 46 to 61)

```python
for doc_id, text in docs.items():
    tokens = tokenize(text)
    self.lengths[doc_id] = len(tokens)
    for term, tf in Counter(tokens).items():
        self.postings.setdefault(term, {})[doc_id] = tf
self.n_docs = len(docs)
self.avgdl = sum(self.lengths.values()) / self.n_docs if self.n_docs else 0.0
```

`BM25` is a **class**: a bundle of data (the index) plus the functions that use it (`idf`, `score`, `search`). `__init__` runs once when you write `BM25(texts)`, and `self.something = ...` stores data on the object.

The data structure is an **inverted index**, stored in `self.postings`. It maps each term to a dictionary of `{doc_id: term frequency}`. For the test corpus, `postings["certificate"]` is `{"a": 1, "d": 3}`: the word appears once in doc a and three times in doc d. "Inverted" because instead of listing the words in each document, it lists the documents for each word, which is what a search needs.

Constructs to notice:

- `Counter(tokens)` (from `collections`) counts how often each token appears. `.items()` gives `(term, count)` pairs.
- `self.postings.setdefault(term, {})` returns the inner dictionary for `term`, creating an empty one first if the term is new. It replaces three lines of "if term not in postings: postings[term] = {}".
- The last line is a **conditional expression** (`x if condition else y`). It guards against dividing by zero when the corpus is empty.

`lengths` (tokens per document) and `avgdl` (average document length) feed the length normalization in `score`. `k1` and `b` are BM25's two tuning knobs, defaulting to the common values 1.2 and 0.75.

## `idf` (lines 63 to 65)

```python
n = len(self.postings.get(term, {}))
return math.log(1 + (self.n_docs - n + 0.5) / (n + 0.5))
```

**Inverse document frequency** measures how rare a term is. `n` is the number of documents containing it (the size of its postings dictionary). `dict.get(term, {})` returns an empty dictionary for a term that isn't in the index, instead of raising `KeyError`, so an unseen query word simply gets `n = 0`.

Worked values on the four-document test corpus: "vpn" is in 3 of 4 documents, so its idf is log(1 + 1.5 / 3.5), about 0.36. "vpn-719" is in 1, so its idf is log(1 + 3.5 / 1.5), about 1.20. The rare code weighs more than three times as much as the common word.

**Why the `1 +`.** The textbook BM25 idf is log((N - n + 0.5) / (n + 0.5)), which goes **negative** for a term in more than half the documents. A negative weight means matching a common word lowers a document's score, which is surprising and can reorder results badly. Lucene (the engine inside Elasticsearch and OpenSearch) adds 1 inside the log so idf is always positive. The test `test_idf_is_lucene_form_and_positive` pins this form. An AI copying the formula from an older source will often produce the textbook version; check for the `1 +`.

## `score` (lines 67 to 75)

```python
norm = self.k1 * (1 - self.b + self.b * dl / self.avgdl)
for term in tokenize(query):
    tf = self.postings.get(term, {}).get(doc_id, 0)
    if tf:
        total += self.idf(term) * tf * (self.k1 + 1) / (tf + norm)
```

For each query term, the document earns idf times a term-frequency factor. Two ideas are packed into that factor:

- **Saturation (`k1`).** tf * (k1 + 1) / (tf + norm) grows with tf but levels off below k1 + 1. Saying "certificate" ten times is not ten times as relevant as saying it once. With `k1 = 0` the factor is constant, so only presence counts.
- **Length normalization (`b`).** `norm` is bigger for documents longer than average, which shrinks their score. A short article that mentions "alpha" is more likely to be about alpha than a long one that mentions it in passing. With `b = 0`, length is ignored.

`test_parameters_do_what_they_claim` checks each of these behaviors directly, which is a good pattern: test what a knob is supposed to do, not just one number.

The chained `.get(term, {}).get(doc_id, 0)` safely returns 0 when either the term or the document is missing. `if tf:` skips terms the document doesn't contain (0 is "falsy" in Python). Note that a query word repeated twice is counted twice; that is a choice, and some implementations deduplicate query terms.

## `search` (lines 77 to 83)

```python
candidates: set[str] = set()
for term in tokenize(query):
    candidates.update(self.postings.get(term, {}))
scored = [(d, self.score(query, d)) for d in candidates]
scored.sort(key=lambda pair: (-pair[1], pair[0]))
return scored[:k]
```

This is where the inverted index pays off. Instead of scoring all 42 documents, it collects only the documents that contain at least one query term. `candidates.update(some_dict)` adds the dictionary's keys (doc ids) to the **set**, which ignores duplicates. A query with no matching terms returns `[]`.

The sort uses `key=` with a **lambda** (a small unnamed function). For each `(doc_id, score)` pair it returns `(-score, doc_id)`, so Python sorts by score descending, then by doc id ascending when scores tie. That tie-break makes results **deterministic**: the same query always gives the same order, which keeps tests and metrics stable. An AI version that sorts with `reverse=True` on the score alone will usually work but can reorder tied documents between runs or Python versions. The same `(-score, id)` key appears in every ranking function in this file.

`scored[:k]` is a **slice**: the first `k` items, or fewer if there aren't that many.

## `cosine` and `vector_search` (lines 89 to 101)

```python
dot = sum(a * b for a, b in zip(u, v))
nu = math.sqrt(sum(a * a for a in u))
nv = math.sqrt(sum(b * b for b in v))
if nu == 0 or nv == 0:
    return 0.0
return dot / (nu * nv)
```

**Cosine similarity** is the dot product divided by the two vector lengths: 1.0 for vectors pointing the same way, 0.0 for perpendicular ones. `zip(u, v)` pairs up the elements of the two lists, and `sum(a * b for ...)` uses a **generator expression** (like a list comprehension without the brackets) to add up the products without building a temporary list.

The zero check prevents a `ZeroDivisionError` on an all-zero vector. The stored vectors are already normalized to length 1, so the division barely matters here, but the function stays correct if you later load unnormalized vectors. A reviewer should check that an AI's "optimization" to just the dot product comes with a guarantee that vectors are normalized.

`vector_search` is **brute force**: score every document, sort with the same `(-score, id)` key, keep the top `k`. With 42 documents that is instant. With millions you would use an approximate index (lesson 3), and this exact version becomes the reference you measure the approximate one against.

## `rrf`: reciprocal rank fusion (lines 107 to 112)

```python
for ranking in rankings:
    for rank, doc in enumerate(ranking, start=1):
        scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + rank)
```

RRF ignores the raw scores entirely and uses only positions. A document earns 1 / (k + rank) from each list it appears in, and the contributions add up. `enumerate(ranking, start=1)` yields `(1, first_doc), (2, second_doc), ...` so ranks start at 1, as the formula expects.

Worked value from the test: doc "a" is 1st in one list and 2nd in the other, so it scores 1/61 + 1/62, about 0.0325. Doc "c" is 3rd and 1st: 1/63 + 1/61, about 0.0323. Close, but "a" wins.

**Why ranks instead of scores.** BM25 scores run from 0 to 15 or so; cosine scores sit between 0 and 1. Adding them directly would let BM25 dominate. Ranks are on the same scale for both lists, so no normalization is needed. The constant `k = 60` (the value from the original RRF paper) flattens the difference between rank 1 and rank 5; a smaller `k` makes the top positions count more.

Watch the name: this `k` is a smoothing constant, not "top k". An AI wiring `hybrid_search` might pass `k=n` here by mistake, which silently changes the fusion.

## `min_max` and `weighted_fusion` (lines 115 to 129)

```python
lo, hi = min(scores.values()), max(scores.values())
if hi == lo:
    return {d: 1.0 for d in scores}
return {d: (s - lo) / (hi - lo) for d, s in scores.items()}
```

Weighted fusion keeps the scores but first rescales each list to 0 to 1 with **min-max normalization**: the best document becomes 1.0, the worst becomes 0.0. Two edge cases are handled explicitly: an empty dictionary returns `{}`, and a list where every score is equal returns all 1.0 instead of dividing by zero.

`weighted_fusion` then walks the score dictionaries alongside their weights with `zip`, normalizes each, and adds `weight * normalized_score` into a running total. `test_weighted_fusion_normalizes_before_weighting` shows why the order matters: with raw scores, a BM25 score of 14.2 would swamp a cosine of 0.83; normalized, the document that is near the top of both lists wins.

Two properties to keep in mind when you read the results:

- A document missing from one list gets nothing from it, the same as the worst-scored document in that list (which normalizes to 0).
- Min-max is sensitive to outliers. One very high BM25 score squashes every other BM25 score toward 0.

## `hybrid_search` (lines 132 to 149)

```python
keyword = bm25.search(query, k=n)
dense = vector_search(query_vec, doc_vecs, k=n)
if method == "rrf":
    fused = rrf([[d for d, _ in keyword], [d for d, _ in dense]])
elif method == "weighted":
    fused = weighted_fusion([dict(dense), dict(keyword)], [alpha, 1 - alpha])
else:
    raise ValueError(f"unknown fusion method: {method!r}")
return [d for d, _ in fused]
```

This is the function the rest of the pipeline calls. It takes the top `n` from each retriever, then fuses them.

- `[d for d, _ in keyword]` unpacks each `(doc, score)` pair and keeps just the doc id. The underscore `_` is the conventional name for a value you are deliberately ignoring.
- `dict(dense)` turns a list of `(doc, score)` pairs into a dictionary, which is what `weighted_fusion` expects.
- `alpha` is the weight on the **vector** list (it comes first) and `1 - alpha` the weight on BM25. With the default 0.5 they count equally. The README asks you to try values from 0.3 to 0.8; this ordering tells you which direction favors which retriever.
- An unknown method raises `ValueError` instead of silently falling back to one of them. `{method!r}` in the f-string shows the value with quotes, so a typo like `'RRF'` is obvious in the error. The test checks that `method="borda"` raises.

Because each list has at most `n` documents, the fused list has between `n` (full overlap) and `2n` (no overlap) documents. The test checks exactly that range for `n = 5`.

## `rerank` (lines 155 to 164)

```python
head = candidates if top_n is None else candidates[:top_n]
tail = [] if top_n is None else candidates[top_n:]
if not head:
    return list(candidates)
scores = model.predict([(query, texts[d]) for d in head])
order = sorted(range(len(head)), key=lambda i: (-float(scores[i]), i))
return [head[i] for i in order] + tail
```

A cross-encoder reads the query and a document together and outputs a relevance score. It is more accurate than comparing two separate embeddings, and much slower, which is why it only reorders a short candidate list.

The `model` argument can be anything with a `predict(pairs)` method. The tests pass a fake that counts shared words; the optional real run passes `sentence_transformers.CrossEncoder`. This is **dependency injection**: the function doesn't create its own model, so tests run offline and instantly.

Design points worth checking in any version you review:

- **One batched call.** All pairs go to `predict` at once. Calling it once per document gives the same answer but is far slower with a real model. The test asserts exactly one call.
- **Pairs are `(query, text)`, in that order.** Cross-encoders are trained on that order.
- **Stable ties.** The sort key `(-score, i)` breaks ties by original position, so two documents the model scores equally keep the order fusion gave them.
- **`top_n` leaves the tail alone.** Candidates past `top_n` are appended unchanged, so reranking the top 20 doesn't drop document 21.
- `float(scores[i])` converts whatever numeric type the model returns into a plain Python float before negating it.

## Metrics: `recall_at_k`, `reciprocal_rank`, `evaluate` (lines 170 to 189)

```python
return sum(1 for d in ranked[:k] if d in relevant) / len(relevant)
...
for i, d in enumerate(ranked[:k] if k else ranked, start=1):
    if d in relevant:
        return 1.0 / i
return 0.0
```

**Recall@k** is the share of relevant documents that appear in the top `k`. With ranking `["a", "b", "c"]`, relevant `{"b", "z"}`, and `k = 2`, one of two relevant documents is found: 0.5. A query with no relevant documents returns 0.0 instead of dividing by zero.

**Reciprocal rank** is 1 divided by the position of the first relevant document: 1.0 if it's first, 0.5 if second, 0 if it's missing from the top `k`. Averaged over queries, that is **MRR**. Note the expression `ranked[:k] if k else ranked`: when `k` is `None` (or 0) the whole list is searched.

`evaluate` averages both over every query in `qrels` (the labeled answers, a name borrowed from information-retrieval tooling). The key line is `results.get(q, [])`: a labeled query that the system returned nothing for counts as a zero rather than being skipped. Skipping it would make a system that fails on hard queries look better than it is. The test `test_evaluate_counts_every_query` checks this, and it is one of the most common mistakes in hand-written evaluation code.

## `run_all` (lines 195 to 212)

```python
configs: dict[str, dict[str, list[str]]] = {"bm25": {}, "vector": {}, "hybrid-rrf": {}, "hybrid-weighted": {}}
if reranker is not None:
    configs["hybrid-rrf+rerank"] = {}
for q in queries:
    qv = vectors["queries"][q["id"]]
    ...
```

This builds the index once, then runs every query through every configuration and stores `{config: {query_id: ranked doc ids}}`. Building the BM25 index outside the loop matters: building it per query would give the same answers 20 times slower.

The query vector is looked up by query id from the precomputed file. That is why the offline pipeline can only answer the 20 labeled queries: there is no embedding model in the loop. The reranked configuration reuses the RRF list (`fused`) rather than running fusion twice, so "rrf" and "rrf + rerank" differ only by the reranker, which is what makes the comparison fair.

## `report`, `load_cross_encoder`, and the script (lines 215 to 242)

```python
groups = {"all": queries, **{t: [q for q in queries if q["type"] == t] for t in types}}
```

`report` groups queries into "all" plus one group per type. The `**{...}` inside a dictionary literal **unpacks** another dictionary into this one. Each row then calls `evaluate` per group. The format specs such as `:<20` (left-align in 20 characters) and `:>17.2f` (right-align, two decimals) line up the table columns.

`load_cross_encoder` imports `sentence_transformers` **inside** the function, not at the top of the file. That keeps the package optional: the lab runs without it, and only `--rerank` needs it.

The `if __name__ == "__main__":` block runs only when you execute the file directly, not when the tests import it. `"--rerank" in sys.argv` checks the command-line arguments for the flag.

## What the tests check

- **Tokenizer and index** (`test_tokenizer_keeps_identifiers`, `test_index_statistics`): identifiers stay whole; postings, lengths, and average length are exactly right on a four-document corpus.
- **BM25 math** (`test_idf_is_lucene_form_and_positive`, `test_score_matches_formula`, `test_parameters_do_what_they_claim`): the always-positive idf, the score formula to nine significant digits, and the behavior of `b = 0` (no length effect), `k1 = 0` (presence only), and saturation.
- **Search** (`test_search_returns_only_matching_docs_sorted`): only matching documents, sorted, respecting `k`, and `[]` for no matches.
- **Vectors and fusion** (`test_cosine_and_vector_search`, `test_rrf_values_and_ties`, `test_min_max_edges`, `test_weighted_fusion_normalizes_before_weighting`, `test_hybrid_search_methods`): exact RRF values and tie-breaks, normalization edge cases, normalize-before-weight, and the error on an unknown method.
- **Reranking with a fake model** (two tests): ordering by model score, one batched call, `(query, text)` pair order, stable ties, and an untouched tail.
- **Metrics** (`test_metrics`, `test_evaluate_counts_every_query`): recall and reciprocal rank values, cutoffs, and that missing queries count as zero.
- **The experiment** (`test_labeled_set_is_consistent`, `test_each_retriever_wins_a_different_slice`, `test_hybrid_is_at_least_as_good_as_either_alone_on_recall`, `test_report_runs`): the data files agree with each other, and the headline findings from the README hold.
- **Optional real cross-encoder**: skipped unless `sentence-transformers` is installed and the model downloads.

What they don't check: the exact numbers in the README table (only the direction of the findings), any `alpha` other than 0.5, behavior on queries outside the labeled set, speed on a large corpus, or whether the labeled set itself is right. Twenty queries is a small set, and the tests can't tell you a configuration will win on real traffic.

## Review questions

1. An AI rewrites `tokenize` as `re.findall(r"[a-z0-9]+", text.lower())`. Which tests fail, and what happens to the identifier slice of the results table?

<details>
<summary>Answer</summary>

Four unit tests fail: `test_tokenizer_keeps_identifiers` (`VPN-719` becomes `vpn` and `719`), `test_index_statistics` (doc "a" now has 6 tokens, not 5), `test_score_matches_formula` (the average document length changes, so the score no longer matches the hand-computed value), and `test_search_returns_only_matching_docs_sorted` (doc "b" now matches through "vpn"). Surprisingly, the identifier slice of the table stays at 1.00 / 1.00 on this data: each right article still contains both "vpn" and "719", and that is enough here. That is the lesson: a small labeled set can miss a real regression, and precise unit tests on the tokenizer are what catch it. Don't accept "the metrics didn't move" as proof a change is safe.

</details>

2. In `hybrid_search`, the weighted branch passes `[dict(dense), dict(keyword)]` with weights `[alpha, 1 - alpha]`. If you want BM25 to count more, do you raise or lower `alpha`?

<details>
<summary>Answer</summary>

Lower it. `alpha` is the weight on the vector list, because the vector dictionary comes first. `alpha = 0.3` gives vectors 0.3 and BM25 0.7. When an AI adds a parameter like this, check which list each weight attaches to; swapped lists are a quiet bug that every test using the default 0.5 would miss.

</details>

3. Why does `evaluate` use `results.get(q, [])` instead of looping over the queries in `results`?

<details>
<summary>Answer</summary>

Looping over `results` would silently skip a labeled query the system returned nothing for, so the average would be taken only over queries that "worked". Looping over `qrels` and defaulting to an empty list counts that query as zero recall and zero reciprocal rank. The denominator is the labeled set, not whatever came back.

</details>

4. `rerank` calls `model.predict` once with every pair. What would change, and what wouldn't, if it called `predict` once per candidate?

<details>
<summary>Answer</summary>

The ranking would be the same (each pair is scored independently), but a real cross-encoder would run much slower, because it processes a batch far more efficiently than many single calls. The test `test_rerank_orders_by_model_scores` also asserts exactly one call, so it would fail. A reviewer should spot per-item model calls inside a loop as a performance bug even when the output is correct.

</details>

5. RRF lost paraphrase recall compared with vectors alone on this set. Looking at the code, why can a useless BM25 list hurt RRF?

<details>
<summary>Answer</summary>

RRF gives every list equal say by rank: the first document in the BM25 list earns 1/61 whether its BM25 score is 12 or 0.4. When BM25's top results match only on a word like "to", those unrelated documents still earn rank credit and can push the right vector result out of the top five. Weighted fusion at least looks at scores (after normalization), and a stop-word list (the CHANGE.md task) removes those junk matches at the source.

</details>
