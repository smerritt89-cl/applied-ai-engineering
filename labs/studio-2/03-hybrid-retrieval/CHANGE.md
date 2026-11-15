# Change: an optional stop-word list for BM25

## The change

The README points at a real weakness: for "suspicious message asking me to wire money", BM25's top five are unrelated articles that share only the word "to", and RRF gives that junk list as much say as the vector list. A common fix is a **stop-word list**: very common words ("a", "the", "to", "for") that are dropped before indexing and before scoring.

Add an optional `stop_words` parameter to `BM25`:

- `BM25(docs, stop_words={"a", "the", "to"})` drops those terms from every document and every query.
- Dropped terms don't count toward document length (so `lengths` and `avgdl` reflect only the kept terms).
- Matching is case-insensitive: `{"The"}` drops "the".
- The default (`stop_words=None`) keeps today's behavior exactly. `tokenize` itself is unchanged, so the tokenizer test still passes.

You'll make the change in `work.py` (your copy of the solution). Once it's in, you can try a stop list on the real data and see whether the paraphrase slice improves without hurting identifiers.

## Write your prompt

Write your own prompt for a coding assistant before you open the example. A good prompt for this change:

- Names the class and the new parameter, with its type and default.
- Says where stop words must be removed (documents **and** queries, in `__init__`, `score`, and `search`) so the assistant doesn't fix only one place.
- States the length rule explicitly. Without it, an assistant may drop stop words from postings but still count them in `lengths`.
- Says what must not change: `tokenize`, the default behavior, the BM25 formula, and the other functions.
- Asks for tests, and says not to change the existing ones.

## Example prompt

<details>
<summary>Show an example prompt</summary>

```text
In work.py, add an optional stop_words parameter to the BM25 class:
BM25(docs, k1=1.2, b=0.75, stop_words=None), where stop_words is a set of strings.

- Terms in stop_words are removed from every document before indexing and from every
  query in score() and search(). Compare case-insensitively (lowercase the stop words once).
- Removed terms do not count toward self.lengths or self.avgdl.
- Put the filtering in one small helper method so __init__, score, and search all use the
  same rule.
- With stop_words=None (the default) behavior must be identical to now.

Do not change tokenize(), the idf or score formulas, or any other function. Do not edit the
existing tests. Update the BM25 docstring to describe the new parameter. Add tests for:
stop words absent from postings, lengths excluding them, a query of only stop words
returning [], case-insensitivity, and the default being unchanged.
```

</details>

## Review the AI's change

- [ ] **Both sides are filtered.** Stop words are removed in `__init__` and in both `score` and `search`. If only the index is filtered, the query term simply finds nothing (harmless but sloppy); if only the query is filtered, the lengths are wrong.
- [ ] **Lengths exclude stop words.** `idx.lengths` and `idx.avgdl` count only kept terms, as specified.
- [ ] **One rule, one place.** The filter lives in a helper, not copied three times. Copies drift apart.
- [ ] **`tokenize` is untouched.** It's a module-level function the tests call directly; putting stop-word removal there would change every caller.
- [ ] **The default is really unchanged.** `stop_words=None` must not be replaced by a built-in English stop list. A "helpful" default would change every number in the results table.
- [ ] **No scope creep.** No new dependency (such as NLTK's stop-word list), no edits to fusion, metrics, or the existing tests. The docstring was updated.

## Check it

From the `labs` folder:

```bash
pytest studio-2/03-hybrid-retrieval/test_change.py -q
pytest studio-2/03-hybrid-retrieval -q
```

The first command runs the acceptance tests for this change (they fail until the change is made). The second runs the full lab to make sure nothing else broke. Then try it on the real data: build `BM25(texts, stop_words={...})` in `run_all` with a short list such as `{"a", "an", "the", "to", "of", "for", "in", "on", "my", "i", "do", "is"}` and compare the paraphrase and identifier columns with the README table.
