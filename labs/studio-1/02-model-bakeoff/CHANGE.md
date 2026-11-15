# Change: a latency budget for the winner

You'll make this change in `work.py` (your copy of `solution.py`), using a coding assistant
such as Claude Code. Then you'll review what it did before running the acceptance tests.

## The change

`pick_winner` chooses the cheapest model that clears the quality bar with zero errors. It looks
at latency only to break exact cost ties. That's fine for an overnight batch job, but many
features have a latency requirement too: a support agent waiting on a suggested reply might
need an answer within 3 seconds at p95, and the cheapest model may not manage that.

Add an optional, **keyword-only** parameter to `pick_winner`:

```python
pick_winner(summary, quality_bar, *, max_p95_s=None)
```

- With `max_p95_s=None` (the default), behavior is exactly what it is today.
- With a number, a model must also have a **measured** p95 latency at or under it
  (`<=`, so exactly at the budget passes). A model whose `p95_latency_s` is `None` cannot be
  shown to meet the budget, so it is excluded.
- Everything else stays: the quality bar, the zero-errors rule, cheapest first, and ties broken
  on p95.

This is the "decide with evidence" habit from the lesson, applied to a second constraint: write
the requirement into the decision rule, so the recommendation can't quietly ignore it.

## Write your prompt

Write your own prompt first, before you open the example. A good one for this change:

- Names the function (`pick_winner`), the new parameter's name, type, default, and that it is
  keyword-only.
- Says whether the limit is inclusive, and what happens when p95 is `None`.
- Says the new rule is an **extra filter**, applied together with the existing ones, not a new
  way of ranking.
- Says what must not change: the default behavior, the tie-break, `summarize`, and the other
  functions.
- Asks for the docstring to be updated, and for tests of each new case plus the unchanged
  default.

<details>
<summary>Example prompt</summary>

```text
In work.py, add a keyword-only parameter to pick_winner:
    def pick_winner(summary, quality_bar, *, max_p95_s: float | None = None)

When max_p95_s is None, behavior must be identical to now. When it is a
number, a model is eligible only if, in addition to the existing rules
(mean_score >= quality_bar and errors == 0), its p95_latency_s is not None
and is <= max_p95_s. Among eligible models, keep the existing ranking: lowest
cost_per_task_usd, then lowest p95, then name.

Don't change summarize, percentile, print_summary, main, or anything else.
Add a docstring to pick_winner describing all the rules, including the new
one. Add tests for: no budget (same winner as today), a budget that rules out
the cheapest model, a p95 exactly at the budget (passes), a budget nobody
meets (None), a model with p95 None and a budget (excluded), and a call that
passes the budget positionally (should raise TypeError).
```

</details>

## Review the AI's change

Read the diff before running anything. Check:

- [ ] **Scope.** Only `pick_winner` changed (signature, docstring, the filter). No edits to
  `summarize`, `percentile`, or the CSV code. If it also added a `--max-p95` command-line flag,
  that's scope creep unless you asked; check it is wired through correctly or ask for it to be
  removed.
- [ ] **Keyword-only with a default.** The parameter comes after a bare `*` and defaults to
  `None`, so `print_summary`'s existing call `pick_winner(summary, quality_bar)` still works.
- [ ] **A filter, not a ranking.** The budget is one more condition in the `if` part of the
  comprehension. The tuple being minimized is still (cost, p95, name).
- [ ] **The `None` case.** A missing p95 is excluded when a budget is set. Watch for
  `s["p95_latency_s"] <= max_p95_s` without a `None` check, which raises `TypeError` on a
  model with no successful calls; and for `(s["p95_latency_s"] or 0) <= max_p95_s`, which
  silently lets an unmeasured model pass.
- [ ] **The boundary.** Exactly at the budget passes (`<=`, not `<`).
- [ ] **Docs and tests.** The docstring describes every rule, and the assistant's tests cover the
  edge cases, not just "a budget changes the winner".

## Check it

From the `labs` folder:

```bash
pytest studio-1/02-model-bakeoff/test_change.py -q
pytest studio-1/02-model-bakeoff -q
```

The first command runs the acceptance tests for this change. The second runs the whole lab, to
make sure nothing else broke. (`change_solution.py` has a reference version if you want to
compare after you've reviewed your own.)

Stretch (no API needed if you already have a `results.csv`): ask the assistant, in a second
prompt, to add a `--max-p95` flag to `main` and pass it through `print_summary`, then run
`--rescore` with and without the flag and see whether the winner changes.
