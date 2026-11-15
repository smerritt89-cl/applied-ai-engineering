# Change: add a p95 latency ceiling to the gate

## The change

The gate already has an optional cost ceiling (`max_cost_ratio`): fail if the candidate costs too much more per
success than the baseline. Your support team has asked for the same protection on speed. A model swap that keeps
quality and cost flat but makes the slowest 5% of replies twice as slow would still hurt customers, and today the gate
would let it through. The report prints p95 latency, but nothing acts on it.

Add an optional setting, `max_p95_latency_ratio`, that works like `max_cost_ratio`:

- It lives in `DEFAULT_CONFIG` with the value `None` (off), so existing configs keep their meaning.
- When set, the gate computes the candidate's p95 latency divided by the baseline's p95 latency, using the existing
  `percentile` helper, and fails if the ratio exceeds the setting.
- The reason starts with `latency:`, shows the ratio with two decimals, and comes after the cost reason (it is check 5
  in the docstring's list).

The work happens in `work.py` (your copy of the solution). Ask a coding assistant to make the change there.

## Write your prompt

Write your own prompt before you open the example. A good prompt for this change:

- Names the file and the function (`gate` in `work.py`) and points at the existing pattern to copy (`max_cost_ratio`).
- Says how the ratio is computed (which percentile, which helper, which direction: candidate over baseline).
- States the reason format and where it goes in the order of checks.
- Says what must **not** change: the default behavior when the setting is absent, the other checks and their order,
  `summarize`, `format_report`, and the CLI.
- Asks for the docstring to be updated, and for tests.

## Example prompt

<details>
<summary>Show the example prompt</summary>

```text
In work.py, add an optional p95 latency ceiling to gate(), modeled on the existing max_cost_ratio check.

1. Add "max_p95_latency_ratio": None to DEFAULT_CONFIG, with a comment like the others.
2. In gate(), after the cost check, if the setting is not None: compute the 95th percentile of latency_s for the
   candidate's results and for the baseline's results with the existing percentile() helper, take
   candidate / baseline, and if the ratio is greater than the setting, append
   f"latency: p95 latency ratio {ratio:.2f} exceeds {setting}".
3. Add this as check 5 in gate()'s docstring.

Do not change any other check, the order of reasons, summarize(), format_report(), main(), or any other function.
With the setting absent or None, the gate must behave exactly as before.

Add tests: the default is None; the faster candidate passes with a ceiling of 1.0; with baseline and candidate
swapped (so the "candidate" is slower) and every other check off, a ceiling of 1.2 fails with exactly one reason
starting "latency:"; and when cost and latency both fail, the cost reason comes first.
```

</details>

## Review the AI's change

Before you accept it, read the diff and check:

- [ ] **Scope.** Only `DEFAULT_CONFIG`, `gate`, and its docstring changed. No new imports, no edits to `summarize`,
      `format_report`, or `main`, and no "while I was here" refactors.
- [ ] **Off by default.** The new key defaults to `None`, and the check is skipped when it is `None` (an `is not None`
      test, not a truthiness test, so a ceiling of `0` would not silently switch the check off).
- [ ] **Right direction.** The ratio is candidate over baseline, matching the cost check. Baseline over candidate would
      fail fast candidates and pass slow ones.
- [ ] **Reuses `percentile`.** It calls the existing nearest-rank helper with 95, rather than adding a second
      percentile implementation (for example `statistics.quantiles`) that gives slightly different numbers.
- [ ] **Order preserved.** The latency reason is appended after the cost reason, and every earlier reason is
      unchanged. Existing tests check `reasons[0]`.
- [ ] **Tests.** New tests cover the off, pass, fail, and ordering cases, and the existing tests still pass.

## Check it

From the `labs` folder:

```bash
pytest studio-3/03-compare-and-gate/test_change.py -q
```

These tests fail until the change is made. Then run the full lab to make sure nothing else broke:

```bash
pytest studio-3/03-compare-and-gate -q
```

You can also try it on the command line by adding `"max_p95_latency_ratio": 1.2` to a copy of
`fixtures/gate_config.json` and running the gate with the baseline and candidate files swapped.
