# Change: flag claims that cite an archived source

## The change

The README's first "What to notice" point is the gap this lab leaves open: the first line of `marked_answer.txt` quotes the archived 2023 FAQ (`faq-020`) word for word, so it passes every check, and it's still the wrong answer. The verifier can't know a source is outdated unless you tell it.

Add an optional `archived` parameter to `verify_answer`, and a new `stale` warning list on `Report`:

- `verify_answer(answer, passages, archived={"faq-020"})` lists, in `report.stale`, the index of every claim that cites at least one **provided** passage whose id is in `archived`. Each claim index appears once, in claim order.
- Stale is a **warning**, like `uncited`. It does not add a `Problem` and does not change `report.ok` or `cited_claims`. A verbatim quote from an archived passage is still a valid citation; it's just a source a human should double-check.
- A citation to an unknown passage is reported as "unknown passage" (as today) and is not also listed as stale.
- With `archived` left out or `None`, `stale` is an empty list and everything else is exactly as before.
- `Report` gets a `stale` field that defaults to an empty list, so existing code that builds a `Report` keeps working.

You'll make the change in `work.py` (your copy of the solution).

## Write your prompt

Write your own prompt for a coding assistant before you open the example. A good prompt for this change:

- Names the function, the new parameter, its type, and its default.
- Says this is a warning, not a problem, and spells out what must stay the same (`problems`, `ok`, `cited_claims`, the order of checks).
- Covers the edge cases: unknown passages, a claim citing the archived passage twice, and the default.
- Says how to add the field to the `Report` dataclass without breaking existing constructors.
- Asks for tests and says not to change the existing ones.

## Example prompt

<details>
<summary>Show an example prompt</summary>

```text
In work.py, extend verify_answer to warn about claims that cite archived sources.

- New signature: verify_answer(answer, passages, archived: set[str] | None = None).
- Add a field to the Report dataclass: stale: list[int], defaulting to an empty list
  (use field(default_factory=list)) so existing Report(...) calls still work.
- report.stale lists the index of each claim with at least one citation to a provided
  passage whose id is in archived. Each index at most once, in claim order. A citation to
  an unknown passage stays an "unknown passage" problem and is not stale.
- stale is a warning only: do not add Problems for it, and do not change ok, cited_claims,
  uncited, abstained, or the order of the existing three checks.
- With archived=None, stale is [].

Update the verify_answer docstring to describe stale. Don't change any other function or the
existing tests. Add tests: the marked_answer.txt fixture with archived={"faq-020"} gives
stale == [0] and the same problems as before; a verbatim archived quote is stale but ok;
a claim citing faq-020 twice is listed once; the default gives [].
```

</details>

## Review the AI's change

- [ ] **Warning, not problem.** No new `Problem` kind was added, and `report.ok` is still true for an answer whose only issue is an archived source.
- [ ] **Existing results unchanged.** `problems`, `uncited`, `abstained`, and `cited_claims` come out the same as before for every fixture. Run the full lab tests.
- [ ] **No duplicates, right order.** A claim citing the archived passage twice appears once in `stale`.
- [ ] **Unknown passages handled.** A citation to an id you never sent is still "unknown passage" and is not also counted as stale.
- [ ] **Safe default.** `Report.stale` uses `field(default_factory=list)`, not `= []` (which dataclasses reject) and not `None` (which forces every caller to check). `archived=None` works.
- [ ] **No scope creep.** No hard-coded `"faq-020"` or "archived in the title" detection inside `verify_answer` (the caller decides what is archived), no changes to the prompt, the parsers, or the API call. The docstring was updated.

## Check it

From the `labs` folder:

```bash
pytest studio-2/04-cited-answers/test_change.py -q
pytest studio-2/04-cited-answers -q
```

The first command runs the acceptance tests for this change (they fail until the change is made). The second runs the full lab to make sure nothing else broke. All of these run offline; no API key needed.

As a follow-up you might try on your own: carry a date or an `archived` flag in `passages.json` and build the `archived` set from the data, instead of typing ids. (`load_passages` would need updating too: `Passage(**p)` rejects keys the dataclass does not define.)
