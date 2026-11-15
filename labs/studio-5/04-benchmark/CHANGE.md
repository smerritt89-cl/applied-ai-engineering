# Change: paired differences per field

## The change

The report gives each system's per-field accuracy, but only exact match gets a paired comparison with the reference.
That leaves the README's most interesting claim untested: "the frontier model is better at detecting items and
owners; the adapter is better at priority". Is the priority gap real, or within the noise of 150 cases? A paired
interval per field answers that.

Ask a coding assistant to add it:

- In `summarize`, every non-reference row gets `"fields_vs_reference"`: a dictionary from each field in `FIELDS` to
  the result of `paired_bootstrap_diff` on that field's per-case 0 or 1 scores (system versus reference, same seed).
  The reference row doesn't get one.
- In `render_report`, after the existing exact-match differences, add a section headed
  `Paired differences per field (percentage points, 95% bootstrap interval):` with one line per non-reference
  system and field, in the same format as the existing lines:
  `- ft-lora vs frontier, priority: +6.7 points [-1.3, +14.7]`.
- Everything already in the report stays as it is, and the caveat about what the intervals cover stays the closing
  line.

When it works, look at the numbers. The adapter's priority advantage is +6.7 points, and its interval includes zero.
So does the frontier model's owner advantage. The per-field story in the README is a reasonable reading of the point
estimates, but at this sample size neither field difference is established on its own. That is exactly the kind of
finding this change exists to surface.

The work happens in `work.py` (your copy of the solution). The tests import it automatically while it exists.

## Write your prompt

Write your own prompt first, before opening the example. A good prompt for this change:

- names the new key and its shape (field name to `{"diff", "lower", "upper"}`), and says to reuse
  `paired_bootstrap_diff` with the same seed rather than writing a new bootstrap;
- says the per-field scores come from each scored case's `"fields"` dictionary, paired on the same cases;
- gives the exact heading and line format for the report, and where the new section goes;
- says what must not change: existing keys, the existing table and lines, the closing caveat, and the scoring and
  interval functions;
- asks for the docstring of `render_report` to list the new lines, and for tests.

## Example prompt

<details><summary>Show the example prompt</summary>

```text
In work.py, add per-field paired comparisons against the reference system.

In summarize, for every non-reference system, add rows[name]["fields_vs_reference"]: a dict mapping
each field in FIELDS to paired_bootstrap_diff([x["fields"][f] for x in s],
[x["fields"][f] for x in scored[reference]], seed=seed). Reuse paired_bootstrap_diff; do not write a
second bootstrap. Don't add the key to the reference row.

In render_report, after the existing "- <system> vs <reference>: ..." lines and their blank line,
add the heading "Paired differences per field (percentage points, 95% bootstrap interval):", a
blank line, and one line per non-reference system and field, formatted exactly like the existing
lines: "- {name} vs {ref}, {field}: {diff:+.1f} points [{lower:+.1f}, {upper:+.1f}]" (values in
percentage points). Then a blank line and the existing closing caveat, unchanged, as the last line.
Add the new lines to the render_report docstring.

Don't change score_run, the metric functions, bootstrap_ci, paired_bootstrap_diff, the table, or
the existing difference lines.

Add tests: every non-reference row has all four fields with lower <= diff <= upper; the values equal
paired_bootstrap_diff on the field scores; ft-lora's priority difference is +10/150 and owner is
-5/150; the report has a line for every system and field; and the existing ft-lora vs frontier
line and the closing caveat are unchanged.
```

</details>

## Review the AI's change

Read the diff before running anything. Check:

- **Paired, not separate.** The per-field comparison calls `paired_bootstrap_diff` on lists in the same case order.
  An implementation that subtracts two separate `bootstrap_ci` intervals, or resamples each system on its own, gives
  intervals that are too wide and is not what was asked.
- **Same seed and procedure.** It passes `seed=seed` and reuses the existing function, so results are reproducible
  and match the docstring's recipe.
- **No self-comparison.** The reference row has no `fields_vs_reference`, and the report has no
  `frontier vs frontier` lines.
- **Format.** The new lines use `:+.1f` in percentage points, like the existing ones, so a reader can compare them
  at a glance.
- **Nothing else moved.** The table, the exact-match lines, and the closing caveat are unchanged, and the caveat is
  still last. Scoring and interval functions are untouched.
- **The interpretation.** If the assistant (or anyone) summarizes the result as "the adapter is better at priority",
  push back: the interval includes zero. The honest summary is "ahead on priority by about 7 points, not
  established at this sample size".

## Check it

From the `labs` folder:

```bash
pytest studio-5/04-benchmark/test_change.py -q
```

Then run the full lab to make sure nothing else broke:

```bash
pytest studio-5/04-benchmark -q
```

Both should pass. Then regenerate the report with `work.py` (the command is in the module docstring) and read the new
section alongside the table.
