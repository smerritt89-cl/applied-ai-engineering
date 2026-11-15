# Change: show how much of the bill is output

You'll make this change in `work.py` (your copy of `solution.py`), using a coding assistant
such as Claude Code. Then you'll review what it did before running the acceptance tests.

## The change

The README's "What to notice" makes a point the report doesn't show: once the prefix is cached,
**output becomes the bill**. On Haiku 5.5, output costs five times base input and a cache read a
tenth of it, so a few hundred output tokens dominate what's left. The next lever is the answer's
length, not the prompt, but nobody will pull that lever unless the report makes it visible.

You want `summarize` to add one new key:

- `"output_cost_share"`: the fraction of the arm's total dollars spent on output tokens (output
  tokens times that model's output price, summed over the arm, divided by the arm's total cost).
  If the arm's total cost is zero, report `0.0` instead of dividing by zero.

And you want `format_report` to show it on each arm's line, right after the read fraction, in the
form `output 64% of cost` (a whole percentage, like the read fraction).

On the fixture, the baseline's share is about 35 percent and the cached arm's about 64 percent:
caching removed most of the input cost, so output is now most of the bill.

## Write your prompt

Write your own prompt first, before you open the example. A good one for this change:

- Names the key, its exact definition, and the zero-cost rule.
- Says to reuse the existing pricing (`request_cost` or the `PRICES` table) instead of hard-coding a
  rate, so it works for every model and stays right when prices change.
- Gives the exact display format for `format_report` and where it goes on the line.
- Says what must not change: the other summary keys and their values, `request_cost`, `compare`,
  and the ratios.
- Asks for the docstring to be updated and for tests, including the zero-cost case.

<details>
<summary>Example prompt</summary>

```text
In work.py, add an "output_cost_share" key to the dict returned by summarize:
the fraction of the arm's total cost that came from output tokens. Compute each
record's output cost with the model's own output price (reuse request_cost, for
example by pricing a usage dict that has only output_tokens, or read PRICES; do
not hard-code a rate). Sum over the arm and divide by the arm's total cost. If
the total cost is 0, return 0.0.

In format_report, show it on each arm's line right after the read fraction, as
"output NN% of cost" using the same {:.0%} formatting as the read fraction.

Don't change request_cost, compare, cache_health, or any existing summary key or
value. Update summarize's docstring to define the new key. Add tests: the share
on the fixture's cached and baseline arms (compute the expected value in the
test from the fixture's tokens and PRICES), a zero-cost arm returns 0.0, and the
report contains "output NN% of cost" for both arms.
```

</details>

## Review the AI's change

Read the diff before running anything. Check:

- [ ] **No hard-coded price.** The output rate comes from `PRICES` (directly or through
  `request_cost`). A literal `0.50` works for Haiku today and is wrong for Sonnet, or after the next
  price change.
- [ ] **Right denominator.** The share divides by the arm's *total cost* (all meters), not by the
  number of requests or by input cost.
- [ ] **Zero-cost case.** An arm whose total cost is 0 returns `0.0`, not a `ZeroDivisionError`.
- [ ] **Untouched behavior.** Every existing key in `summarize` has the same value as before, and
  `compare`'s ratios are unchanged. `request_cost` itself is not modified.
- [ ] **The report line.** The new text sits after the read fraction and uses the requested
  format. Watch for an extra key that breaks `format_report` for an arm with no timings.
- [ ] **Docs and tests.** The docstring defines the key, and the tests compute the expected
  value independently rather than calling the new code to produce it.

## Check it

From the `labs` folder:

```bash
pytest studio-6/02-cost-latency/test_change.py -q
pytest studio-6/02-cost-latency -q
```

The first command runs the acceptance tests for this change. The second runs the whole lab, to
make sure nothing else broke. (`change_solution.py` has a reference version if you want to
compare after you've reviewed your own.)

Stretch (needs an API key): run `python studio-6/02-cost-latency/work.py` and look at the output
share on your live run. Then lower `MAX_TOKENS` or ask for shorter answers in `INSTRUCTIONS`, rerun,
and see how much the cached arm's cost moves compared with what caching saved.
