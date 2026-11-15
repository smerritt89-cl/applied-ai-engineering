# Change: break the pass rate down by channel or plan

## The change

The report gives one pass rate for the whole sample. Your support lead asks a fair follow-up: "Is the bot worse on email than on chat? Worse for Pro customers?" Every trace already carries a `channel` and a `plan`, so the data to answer this is sitting there unused.

Add two things to the toolkit:

1. A new function `pass_rate_by(traces, annotations, field)` that returns, for each value of `field`, how many traces were annotated, how many passed, and the pass rate, as `{value: {"annotated": n, "passed": p, "pass_rate": p / n}}`. Only `"channel"` and `"plan"` are allowed (keep them in a module-level `SEGMENT_FIELDS` tuple); anything else raises `ValueError`. Only annotated traces count. Keys are sorted A to Z.
2. A new optional argument `segment_by` on `render_report`. When it is given, the report gets a `## Pass rate by {segment_by}` section, placed after the top issues (and after "Needs axial coding" if present) and before "Caveats", with a table headed `| {segment_by} | Annotated | Passed | Pass rate |` and rows like `| email | 4 | 1 | 25.0% |`. When it is not given, the report is exactly as before.

On the reference data, chat passes 12 of 32 (37.5%) and email 1 of 4 (25.0%). That gap looks interesting, and the email number rests on four traces. Your caveats already say why that matters.

You make the change in `work.py` (your copy of the solution), not in `solution.py`.

## Write your prompt

Write your own prompt for a coding assistant before you open the example. A good prompt here:

- Names the file (`work.py`) and the two pieces: the new function and the new argument.
- Gives the exact return shape and the exact table header and row format, so you don't get a near miss that breaks the tests.
- Says what to do with an unknown field and with traces that have not been annotated.
- Says where in the report the section goes, and that the default report must not change.
- Asks it to reuse existing code (`summarize`) instead of re-deriving pass rates.
- Says what must not change: the other functions, the existing report sections, the existing tests.

## Example prompt

<details>
<summary>Show the example prompt</summary>

```text
In studio-3/01-error-analysis/work.py, add a pass-rate breakdown by segment.

1. Add a module-level SEGMENT_FIELDS = ("channel", "plan") and a function
   pass_rate_by(traces, annotations, field) -> dict[str, dict].
   - Raise ValueError if field is not in SEGMENT_FIELDS.
   - Group the annotations by the matching Trace's field value (look traces up by trace_id).
   - For each value return {"annotated": n, "passed": p, "pass_rate": p / n}, reusing summarize().
   - Only annotated traces count. Return keys sorted A to Z.
   - Give it a docstring in the same style as the others.

2. Add an optional keyword argument segment_by: str | None = None to render_report.
   When it is set, add a section after "Top issues" and after "Needs axial coding" (if present),
   and before "Caveats":
       ## Pass rate by {segment_by}
       | {segment_by} | Annotated | Passed | Pass rate |
       |---|---|---|---|
       | chat | 32 | 12 | 37.5% |
   Format the rate with :.1% like the existing table. Update the docstring's numbered list.
   When segment_by is None the report must be byte-for-byte what it is today.

Do not change any other function, the existing report sections, or the existing tests.
Do not add new imports. Then run pytest studio-3/01-error-analysis -q and
pytest studio-3/01-error-analysis/test_change.py -q and show me the output.
```

</details>

## Review the AI's change

Before you accept it, read the diff and check:

- **Scope.** Only `pass_rate_by`, `SEGMENT_FIELDS`, and the `render_report` signature, docstring, and new section changed. No "while I was here" rewrites of other functions or reformatting of untouched lines.
- **Default unchanged.** With no `segment_by`, the report is identical. A new section that always prints, or a reordered existing section, is a regression even if the tests you wrote don't notice.
- **Field validation.** An unknown field raises `ValueError`. Watch for a version that calls `getattr(t, field)` with no check, which would happily group by `bot_response` and print 36 rows of text.
- **Denominator.** Rates divide by annotated traces in each segment, not by all traces in that segment. A half-annotated sheet would otherwise look much worse than it is.
- **Reuse.** It uses `summarize` (or the same logic) rather than a second, slightly different pass-rate calculation that could drift.
- **Docs.** The `render_report` docstring lists the new section in the right position, and the new function has a docstring that states the return shape.

## Check it

From the `labs` folder:

```bash
pytest studio-3/01-error-analysis/test_change.py -q
```

Then run the full lab tests to make sure nothing else broke:

```bash
pytest studio-3/01-error-analysis -q
```

Finally, run `render_report(..., segment_by="plan")` on the reference data and read the section. Ask yourself whether a 2.5-point gap between Pro and Starter on 36 traces is worth acting on.
