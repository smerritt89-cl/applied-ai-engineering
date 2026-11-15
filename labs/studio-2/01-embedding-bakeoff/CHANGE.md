# Change: treat small differences as ties in `compare_per_query`

## The change

`compare_per_query` calls a query a win for one model whenever its reciprocal rank is higher, by any amount. On a small labeled set that overstates differences: a model that puts the right article fourth (0.25) "beats" one that puts it fifth (0.2), and the head-to-head count makes the two models look further apart than they are.

Add a `min_delta` parameter to `compare_per_query`:

- A query is a win only when one reciprocal rank is higher than the other by **more than** `min_delta`. A gap equal to or smaller than `min_delta` is a tie.
- The default is `0.0`, which keeps today's behavior exactly (any difference is a win).
- A negative `min_delta` raises `ValueError`.
- The existing check that both reports cover the same queries stays.
- Optionally, add a `--min-delta` option to the script so you can pass it from the command line.

The work happens in `work.py` (your copy of `solution.py`).

## Write your prompt

Write your own prompt for a coding assistant first, then compare it with the example below. A good prompt for this change:

- Names the function and the new parameter, with its type and default.
- States the boundary rule precisely ("more than", so equal counts as a tie). Vague wording like "ignore small differences" invites a different rule.
- Says what must not change: the default behavior, the output dict shape and key names, the query order, and the different-queries `ValueError`.
- Asks for the docstring to be updated and for tests of the new cases.
- Limits scope: only `compare_per_query` (and, if you want it, the CLI option that passes it through).

## Example prompt

<details>
<summary>Show the example prompt</summary>

```text
In work.py, add a keyword parameter min_delta: float = 0.0 to compare_per_query.

New rule: a query counts as a win for a report only if its reciprocal rank is higher
than the other report's by MORE than min_delta. A gap equal to or smaller than
min_delta is a tie. Raise ValueError if min_delta is negative.

Do not change anything else about the function: with the default of 0.0 it must
behave exactly as it does now. Keep the output keys ("a_wins", "b_wins", "ties"),
keep query ids in the order of a.results, and keep the ValueError for reports that
cover different queries. Update the docstring to describe min_delta and the
boundary rule.

Also add a --min-delta command-line option in main (default 0.0) and pass it to
compare_per_query. Do not change any other function.

Add tests for: a small gap becoming a tie, a gap exactly equal to min_delta being a
tie in both directions, the default behaving as before, and a negative min_delta
raising ValueError.
```
</details>

## Review the AI's change

- [ ] **Scope.** Only `compare_per_query` (and the optional CLI option) changed. `rank`, the metrics, `evaluate`, and `Report` are untouched.
- [ ] **Boundary.** The comparison is `difference > min_delta`, not `>=`. A gap exactly equal to `min_delta` is a tie, in both directions.
- [ ] **Default unchanged.** With `min_delta=0.0`, results match the old version, including ties for equal reciprocal ranks.
- [ ] **Validation.** A negative `min_delta` raises `ValueError`, and it is checked before any work is done.
- [ ] **Nothing removed.** The different-queries check, the lookup by query id (not by position), and the output order are still there.
- [ ] **Docs and tests.** The docstring explains the new parameter and its rule, and new tests cover the tie, the boundary, and the error.

Watch for one specific mistake: comparing `abs(ra.rr - rb.rr) > min_delta` and then deciding the winner in a second step is fine, but an assistant sometimes writes `if ra.rr > rb.rr + min_delta` for A and forgets the matching `+ min_delta` for B, so small gaps become ties only in one direction. The boundary test catches that.

## Check it

From the `labs` folder:

```bash
pytest studio-2/01-embedding-bakeoff/test_change.py -q
pytest studio-2/01-embedding-bakeoff -q
```

The first command runs the acceptance tests for this change; they fail until the change is made. The second runs the lab's full suite to make sure nothing else broke.
