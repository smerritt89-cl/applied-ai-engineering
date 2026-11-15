# Walkthrough: the embedding bake-off

## What this code does

This lab answers a practical question: given a few embedding models, which one finds the right help-center article for the questions your users actually ask? It does that the way you'd want any vendor claim checked, with a small labeled test set and two standard scores.

The file has four layers. Data loading reads 20 articles and 16 labeled queries. Vector math (`normalize`, `cosine`, `rank`) turns "how similar are these two texts" into a sorted list of article ids. Metrics (`recall_at_k`, `reciprocal_rank`) score one ranked list against the labels. Evaluation (`evaluate`, `compare_per_query`, `failures`, `summary_table`) runs a whole model over the whole set and summarizes it. At the bottom are the embedder adapters (one small function per model or provider) and a command-line entry point.

The key design idea is that every embedder has the same shape: a function that takes a batch of texts and a role (`"query"` or `"document"`) and returns one vector per text. Because of that, the evaluation code never needs to know which model it is scoring, and the tests can pass in a fake embedder with hand-picked vectors.

## How to read this lab

Open `work.py` beside this page. It starts as an exact copy of `solution.py`, so the line numbers below match it until you edit it. Run the tests from VS Code's **Testing** panel (the flask icon); they should all pass against `work.py`. The two "optional" tests need extra packages or keys and are skipped otherwise.

Read in order: the type aliases first, because they name the shapes everything else passes around, then vectors, metrics, evaluation, and finally the adapters.

## Imports and type aliases (lines 9 to 26)

```python
from __future__ import annotations
...
Vector = list[float]
Embedder = Callable[[Sequence[str], str], list[Vector]]
```

`from __future__ import annotations` (line 9) tells Python not to evaluate type hints at import time. It lets the file use modern hint syntax such as `int | None` everywhere and costs nothing at run time.

Lines 24 and 26 are **type aliases**: names for shapes. `Vector` is just a list of floats. `Embedder` reads as "a callable that takes a sequence of strings and a string, and returns a list of vectors". `Callable` and `Sequence` come from the `typing` module (line 19). `Sequence` is deliberately looser than `list`: it accepts a list or a tuple, which is what a function that only reads its input should ask for.

Type hints are not enforced when the code runs. They are documentation that editors and tools can check. When you review AI-written code, hints are a fast way to see whether a function's inputs and outputs match what its callers pass in.

`HERE` and `DATA` (lines 21 and 22) use `pathlib.Path(__file__).parent`, which means "the folder this file lives in". That makes the data paths work no matter which folder you run the script from. A hard-coded relative path like `"data/corpus.json"` is a common AI-written bug: it works only when you start Python in exactly the right folder.

## Data loading (lines 32 to 44)

```python
def document_text(doc: dict) -> str:
    return f"{doc['title']}. {doc['text']}"
```

`load_corpus` and `load_queries` read JSON files into lists of dicts. `document_text` decides what gets embedded for an article: its title, a period, then its body. The `f"..."` string is an **f-string**: anything in braces is evaluated and inserted.

That one line is a real modeling decision. Titles are dense with the words people search for, so including them usually helps. If you ever change what you embed (add tags, drop the title), every score in this lab can move, which is why it lives in one small, named function instead of being repeated inline.

## `norm` and `normalize` (lines 50 to 59)

```python
def norm(v):
    return math.sqrt(sum(x * x for x in v))

def normalize(v):
    n = norm(v)
    if n == 0:
        raise ValueError("cannot normalize a zero vector")
    return [x / n for x in v]
```

`norm` is the vector's length: the square root of the sum of squares. `sum(x * x for x in v)` uses a **generator expression**, which is like a list comprehension without the square brackets. It produces values one at a time for `sum` to add, without building a list first.

`normalize` divides every element by the length, so the result has length 1. For `[3, 4]` the length is 5 and the result is `[0.6, 0.8]`. The `[x / n for x in v]` part is a **list comprehension**: "for each x in v, compute x / n, and collect the results in a list".

The zero check matters. Dividing by zero would crash with `ZeroDivisionError`, which is a confusing message. Raising `ValueError` with a sentence says what went wrong and is what the test expects.

## `cosine` (lines 62 to 69)

```python
if len(a) != len(b):
    raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")
na, nb = norm(a), norm(b)
...
return sum(x * y for x, y in zip(a, b)) / (na * nb)
```

Cosine similarity is the dot product divided by both lengths. It measures the angle between two vectors and ignores how long they are, so `[1, 2, 3]` and `[2, 4, 6]` score exactly 1.0.

`zip(a, b)` pairs up the elements of two lists position by position. Here is the trap it hides: if the lists have different lengths, `zip` silently stops at the shorter one. Without the length check on line 64, comparing a 384-dimension vector against a 1,024-dimension vector would quietly return a number. That happens in real systems when someone switches embedding models and forgets to re-embed the stored documents. The check turns a silent wrong answer into a loud error. If an AI "simplifies" this function, make sure the check survives.

`na, nb = norm(a), norm(b)` is **tuple unpacking**: compute two values and assign them to two names in one line.

## `rank` (lines 72 to 77)

```python
scored = sorted(
    ((cosine(query_vec, v), doc_id) for v, doc_id in zip(doc_vecs, doc_ids)),
    key=lambda t: (-t[0], t[1]),
)
ranked = [doc_id for _, doc_id in scored]
return ranked if k is None else ranked[:k]
```

This builds a pair `(score, doc_id)` for every document, sorts them, then keeps just the ids.

`sorted(..., key=...)` sorts by whatever the key function returns. The key here is a **lambda**, a small unnamed function: `lambda t: (-t[0], t[1])` takes a pair and returns `(negative score, id)`. Python sorts tuples element by element, so this means "highest score first, and when two scores are equal, alphabetical by id". Negating the score is the usual trick for "descending on one field, ascending on another" in a single sort.

The tie-break is not cosmetic. With a keyword baseline, many documents can score exactly the same, and without a rule the order depends on the input order. Then recall can change between two runs that should be identical, which makes comparisons between models meaningless.

`[doc_id for _, doc_id in scored]` unpacks each pair and keeps the second item. The underscore is a convention for "a value I don't need". The last line is a **conditional expression**: return everything if `k` is `None`, otherwise the first `k`. `k: int | None = None` in the signature is a **default argument** with a type hint saying it may be an integer or `None`.

## `recall_at_k` (lines 83 to 90)

```python
relevant = set(relevant)
...
return len(set(ranked[:k]) & relevant) / len(relevant)
```

Recall@k is "what share of the right answers appear in the top k". If a query has two relevant articles and one is in the top 3, recall@3 is 0.5.

Converting to a `set` (line 85) lets the function accept a list or a set, and makes `&` (set intersection, "items in both") available. Sets also ignore duplicates, so a ranked list can't get extra credit by repeating an id.

The two checks prevent quiet nonsense. An empty `relevant` would divide by zero; more importantly, a query with no labels is a data problem you want to hear about, not skip. `k < 1` makes no sense as "top k". Note that a `k` bigger than the list is fine: `ranked[:10]` on a three-item list just returns all three.

## `reciprocal_rank` (lines 93 to 99)

```python
for position, doc_id in enumerate(ranked, start=1):
    if doc_id in relevant:
        return 1.0 / position
return 0.0
```

Reciprocal rank rewards putting the first right answer near the top: 1.0 if it is first, 0.5 if second, about 0.333 if third, and 0 if it never appears. Averaged over queries, it is **MRR** (mean reciprocal rank).

`enumerate(ranked, start=1)` gives each item with a counter. The default start is 0, and `start=1` makes the positions human-style (first, second, third). Forgetting `start=1` is a classic off-by-one bug: the top result would be at position 0, and `1.0 / 0` crashes. An AI that "fixes" the crash with `1.0 / (position + 1)` gets correct numbers but has made the code harder to read and easier to break.

Returning inside the loop stops at the first relevant hit, which is the definition: later relevant documents don't count.

## `QueryResult` and `Report` (lines 102 to 122)

```python
@dataclass
class Report:
    name: str
    ks: tuple[int, ...]
    results: list[QueryResult] = field(default_factory=list)
```

`@dataclass` is a **decorator** that writes the boring parts of a class for you: the constructor that takes each field, a readable printout, and equality comparison. You list the fields with type hints and get a class that holds data.

`field(default_factory=list)` gives each new `Report` its own empty list. Writing `results: list = []` instead is a well-known Python bug in ordinary classes (every instance would share one list), and dataclasses refuse it outright. `tuple[int, ...]` means "a tuple of any number of integers".

`mean_recall` and `mrr` are **methods**: functions attached to the class that read its `results`. They average per-query values, which is exactly where the README's warning applies: with 16 queries, one query changes recall by more than 6 points.

## `evaluate` (lines 125 to 148)

```python
doc_vecs = embedder([document_text(d) for d in corpus], "document")
query_vecs = embedder([q["query"] for q in queries], "query")
if len(doc_vecs) != len(corpus) or len(query_vecs) != len(queries):
    raise ValueError("embedder returned the wrong number of vectors")
```

This is the heart of the lab. It makes exactly two embedder calls: one for all articles with role `"document"`, one for all queries with role `"query"`. Then for each query it ranks the whole corpus and stores a `QueryResult`.

Why exactly two calls:

- **Cost and speed.** Provider APIs charge per token and limit requests per minute. Embedding the corpus once per query (an easy mistake inside the loop) would make 16 copies of the same work. The test `test_evaluate_batches_once_per_role` uses a fake embedder that records its calls, precisely to catch that.
- **Roles.** Some models embed questions and passages differently (Voyage's `input_type`, E5's `query: ` and `passage: ` prefixes). Passing the role on every call is what lets those models work as designed. Swapping the roles raises no error; it just lowers the scores, so it is the kind of bug only a test catches.

The count check on line 133 protects the `zip` on line 136. If a provider silently dropped one text (say, an empty string), `zip` would pair the remaining vectors with the wrong queries and every score after that would be wrong. The check fails loudly instead.

Inside the loop, `{k: recall_at_k(ranked, q["relevant"], k) for k in ks}` is a **dict comprehension**: it builds `{1: ..., 3: ..., 5: ...}` in one expression. The function ranks the whole corpus (no `k`), so every cutoff is computed from the same list.

## `compare_per_query` (lines 151 to 167)

```python
b_by_id = {r.query_id: r for r in b.results}
if set(b_by_id) != {r.query_id for r in a.results}:
    raise ValueError("reports cover different queries")
...
if ra.rr > rb.rr:
    out["a_wins"].append(ra.query_id)
elif rb.rr > ra.rr:
    out["b_wins"].append(ra.query_id)
else:
    out["ties"].append(ra.query_id)
```

Averages hide which queries a model wins. This function lines two reports up query by query and sorts each query into a win for A, a win for B, or a tie, by reciprocal rank.

It first builds a lookup dict from B's results keyed by query id, so it can match queries by id rather than by position. Matching by position (zipping the two lists) would silently give wrong answers if the two reports were built from differently ordered query files. The set comparison (`{...}` with no colon is a **set comprehension**) refuses to compare reports that don't cover the same queries.

The output lists keep A's query order, so the result is deterministic and readable.

## `failures` and `summary_table` (lines 170 to 183)

```python
return [r for r in report.results if not set(r.ranked[:k]) & set(r.relevant)]
```

`failures` lists the queries with nothing relevant in the top k. An empty set is "falsy" in Python, so `not (empty intersection)` is `True`, and those queries are kept. This is the list you actually read when choosing a model: the averages say how much, the failures say what.

`summary_table` builds a small Markdown table with string joins and f-strings. `f"{value:.3f}"` formats a number to three decimal places. `*rows` inside the list on the last line **unpacks** the rows into the surrounding list.

## The keyword baseline: `hashing_embedder` (lines 188 to 211)

```python
def hashing_embedder(dim: int = 512) -> Embedder:
    def embed(texts, role):
        ...
        v[zlib.crc32(tok.encode()) % dim] += 1.0
        ...
    return embed
```

This is a model-free baseline. It lowercases the text, pulls out words with a **regular expression** (`TOKEN` on line 188 matches runs of letters and digits, allowing internal hyphens so `e-417` stays one token), drops common words, and counts each word into one of 512 buckets chosen by a hash. Two texts score high only when they share words.

`hashing_embedder` returns a function, `embed`. A function defined inside another function and returned is a **closure**: it remembers `dim` from the outer call. This is how every adapter in the file gets the same `Embedder` shape, with its settings baked in.

The docstring explains a subtle choice: `zlib.crc32` instead of Python's built-in `hash()`. Python randomizes `hash()` for strings each time it starts, so vectors would differ between runs. An AI tidying this code might swap in `hash()` because it looks simpler; the results would then change from run to run.

`normalize(v) if any(v) else v` skips normalizing an all-zero vector (a text made only of stopwords), which would otherwise raise.

## Model and provider adapters (lines 214 to 264)

```python
def voyage_embedder(model: str = "voyage-4-lite") -> Embedder:
    import voyageai
    client = voyageai.Client()
    def embed(texts, role):
        result = client.embed(list(texts), model=model, input_type=role)
        return [list(map(float, e)) for e in result.embeddings]
    return embed
```

Each adapter wraps one model in the shared `Embedder` shape. Three things to notice:

- **Imports inside the function.** `sentence_transformers`, `voyageai`, and `openai` are imported only when that adapter is used. The offline tests and the `hashing` run therefore work without installing any of them. `main` catches the resulting `ImportError` and prints a helpful message.
- **Roles are mapped per provider.** The Sentence Transformers adapter turns the role into a text prefix (used by E5, empty for MiniLM). The Voyage adapter passes it as `input_type`. The OpenAI adapter ignores it because those models embed queries and documents the same way, as its docstring says.
- **Output is converted to plain floats.** `list(map(float, row))` turns NumPy numbers or SDK objects into ordinary Python floats, so the rest of the code never depends on a provider's types. The OpenAI adapter also sorts results by `index` before returning, so vectors line up with the input texts even if the response came back in a different order.

`EMBEDDERS` (lines 258 to 264) maps names to functions that build an embedder. The `e5` entry is a `lambda` because it needs arguments (the model name and its prefixes) filled in.

## `main` and the script entry point (lines 267 to 305)

`argparse` (lines 268 to 271) reads command-line options such as `--embedders hashing,minilm`. The loop builds and evaluates each embedder inside `try`/`except`: an `ImportError` means a package is missing, and the broad `except Exception` covers a missing key, a network error, or a rate limit. Either way it prints why and moves on, so one broken provider doesn't stop the whole comparison.

A broad `except Exception` is usually a red flag in review because it can hide real bugs. Here it is a deliberate, commented choice in a command-line report. It would be wrong inside `evaluate`, where hiding an error would produce a misleading score.

`if __name__ == "__main__":` (line 297) runs only when you execute the file as a script, not when the tests import it. It loads `labs/.env` if it exists, so provider keys are available.

## What the tests check

- **Vector math** (`test_normalize_*`, `test_cosine_*`, `test_rank_*`): unit length, zero-vector and dimension errors, that cosine ignores length, that ranking uses cosine rather than the raw dot product, and that ties go to the alphabetically first id.
- **Metrics** (`test_recall_*`, `test_reciprocal_rank`): worked values, including k larger than the list, only the first relevant hit counting for reciprocal rank, and the empty-label and bad-k errors.
- **Evaluation** (`test_evaluate_*`, `test_compare_*`, `test_failures_*`): a fake embedder with hand-picked vectors makes every ranking known in advance, so the tests can check exact rankings, recall, MRR, the two-call batching with the right roles, and the wrong-vector-count error.
- **The real data set**: every label points at an article that exists, and the keyword baseline finds the exact error code but misses the Spanish query, with an MRR in a plausible middle range.
- **Optional real models**: the local MiniLM test (if installed) and the live Voyage test check unit-length vectors and a minimum recall@5.

What they don't check: whether the labels themselves are right, whether 16 queries are enough to decide (they aren't, as the README says), the CLI output, or the OpenAI and E5 adapters. A model that wins here has passed a small smoke test, not earned a production decision.

## Review questions

1. An AI rewrites `rank` to sort with `key=lambda t: t[0], reverse=True`. What changes, and would the tests notice?

<details>
<summary>Answer</summary>

Scores still sort highest first, but ties are no longer broken by id: equal scores keep their input order (Python's sort is stable, and `reverse=True` preserves the original order of equal elements). `test_rank_breaks_ties_by_id_and_truncates` would fail, because it expects `["a", "b", "c"]` for documents given as `b, a, c` with equal cosines for `a` and `b`. In real runs, results for tied keyword scores would depend on file order.
</details>

2. Why does `evaluate` check the number of vectors the embedder returned, when a correct embedder always returns one per text?

<details>
<summary>Answer</summary>

Because the next step pairs vectors with queries using `zip`, which silently stops at the shorter list. If an embedder dropped or merged a text, every later query would be scored against the wrong vector, and the report would look normal. The check turns that into an immediate `ValueError`. Defending the boundary with an external service is cheaper than debugging a wrong number later.
</details>

3. A colleague moves the corpus embedding call inside the `for q, qv in ...` loop "so each query gets fresh document vectors". What breaks?

<details>
<summary>Answer</summary>

The scores stay the same (the document vectors don't change), but the cost and time multiply by the number of queries, and a provider's rate limit is hit much sooner. `test_evaluate_batches_once_per_role` fails, because the fake embedder records one document call per query (three in that test) instead of one.
</details>

4. Model B has a higher MRR than model A on this set. What should you look at before choosing B?

<details>
<summary>Answer</summary>

The per-query comparison and the failure lists. With 16 queries, a difference in means can come from one or two queries. Check which queries B wins and loses, whether those are the kinds of questions your users ask (the error code, the Spanish query, paraphrases), and whether B now misses something A got right, such as ranking E-416 above E-417. Then grow the test set with real user queries before deciding.
</details>
