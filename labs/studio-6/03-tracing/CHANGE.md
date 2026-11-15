# Change: list the slowest traces on the dashboard

You'll make this change in `work.py` (your copy of `solution.py`), using a coding assistant
such as Claude Code. Then you'll review what it did before running the acceptance tests.

## The change

The dashboard tells you the trace p95 is, say, 9,000 ms, but not *which* traces were slow. The
README's point that "the trace id joins everything" only pays off if the dashboard hands you a
trace id to look up. Right now you'd have to open the JSONL and sort it yourself.

You want:

- `aggregate` to return a new key, `"slowest_traces"`: a list of up to three dicts,
  `{"trace_id": ..., "latency_ms": ...}`, for the slowest traces by **per-trace latency** (the sum
  of the trace's steps, the same number `trace_p95_ms` is computed from). Slowest first. If two
  traces tie, the one with the smaller trace id comes first, so the output is stable. A log with
  fewer than three traces lists fewer; an empty log gives an empty list.
- `render_markdown` to add a section after the table and before the closing "Percentiles are
  nearest-rank..." line:

  ```text
  Slowest traces:
  - t2: 30,300 ms
  - t1: 2,100 ms
  ```

  with one line per entry, using the same `_fmt_ms` formatting as the rest of the dashboard.

Everything already on the dashboard stays exactly as it is.

## Write your prompt

Write your own prompt first, before you open the example. A good one for this change:

- Defines "slowest" precisely (sum of steps per trace, not the slowest single call), and says
  to reuse the per-trace latency the function already computes.
- States the limit (three), the order, and the tie-break.
- Gives the exact dashboard format and where it goes.
- Says what must not change: the existing keys and values of `aggregate`, the headline lines,
  the table header and rows (the existing tests check them character for character).
- Asks for docstring updates (both functions document their output) and tests, including a tie
  and a log with fewer than three traces.

<details>
<summary>Example prompt</summary>

```text
In work.py, add a "slowest_traces" key to the dict returned by aggregate: a
list of up to 3 dicts {"trace_id": str, "latency_ms": number} for the traces
with the highest per-trace latency, where per-trace latency is the sum of that
trace's records' latency_ms (the same values trace_p50_ms and trace_p95_ms use;
compute them once and reuse them). Sort slowest first; break ties by trace_id
ascending. Fewer than 3 traces lists fewer; an empty log gives [].

In render_markdown, after the table and before the "Percentiles are
nearest-rank..." line, add a blank line, then "Slowest traces:", then one line
per entry: "- {trace_id}: {_fmt_ms(latency_ms)}".

Don't change any existing key or value in aggregate, the headline lines, or
the table. Update both docstrings. Add tests for: a small log where the
slowest trace is slow because of one failed 30-second step, a tie on latency,
an empty log, and the rendered section's exact text and position.
```

</details>

## Review the AI's change

Read the diff before running anything. Check:

- [ ] **The right latency.** "Slowest trace" uses the sum of the trace's steps, not the slowest
  single record. A version that sorts records by `latency_ms` and takes the top three can list
  the same trace twice, or miss a trace made slow by two medium steps.
- [ ] **One computation.** The per-trace sums are computed once and reused for the percentiles and
  the new list, so the two can never disagree.
- [ ] **Failed calls included.** A trace with a slow error step still counts as slow, consistent
  with the rest of `aggregate`. Watch for a filter on `status == "ok"` sneaking in.
- [ ] **Stable order.** The tie-break is implemented (for example, sorting on
  `(-latency, trace_id)`), not left to dictionary order.
- [ ] **Untouched output.** The existing tests still pass: the headline lines, the table header,
  and the rows are byte for byte the same.
- [ ] **No content.** The new section shows trace ids and latencies only, no previews or user
  ids. The dashboard is the kind of thing that gets pasted into a weekly review.

## Check it

From the `labs` folder:

```bash
pytest studio-6/03-tracing/test_change.py -q
pytest studio-6/03-tracing -q
```

The first command runs the acceptance tests for this change. The second runs the whole lab, to
make sure nothing else broke. (`change_solution.py` has a reference version if you want to
compare after you've reviewed your own.)

Then render the sample dashboard (`python studio-6/03-tracing/work.py dashboard
studio-6/03-tracing/samples/sample_log.jsonl`) and find the slowest trace's records in
`samples/sample_log.jsonl`. Which step made it slow?
