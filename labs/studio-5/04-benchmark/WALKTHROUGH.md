# Walkthrough: Lab 04, benchmark your model against a frontier model

## What this code does

This lab turns three recorded runs (your LoRA-tuned small model, the same model without the adapter, and a
frontier API model) into a benchmark report that would survive a skeptical review. Every run answered the same 150
frozen test cases; the code scores them field by field, puts an interval around each headline number, compares each
system with a reference using a **paired** interval, prices each system per 1,000 tasks, and summarizes latency.

The structure follows the questions a reviewer asks, in order. **Is this a fair comparison?** The integrity checks
in `score_run` refuse runs made on a different test set, runs with duplicate ids, and runs with missing cases.
**How good is each system?** Per-field accuracy, exact match, and parse rate, with unparseable outputs kept in the
denominator. **How sure are we?** Bootstrap intervals. **What does it cost, and how fast is it?** Cost per 1,000
tasks and latency percentiles. Then everything is rendered as Markdown.

It uses only the standard library, and every random step is seeded. Run it twice on the same inputs and you get the
same report, which is what makes it reviewable.

## How to read this lab

Open `work.py` in VS Code beside this page. It starts as a copy of `solution.py`, so the line numbers below match
it until you edit it. Read a section here, then the same lines there.

Run the tests from VS Code's **Testing** panel (the flask icon): expand `studio-5/04-benchmark` and press run. All
tests are offline. From a terminal: `pytest studio-5/04-benchmark -q` from the `labs` folder. To see the report,
run the command in the module docstring (lines 8 to 9) with `work.py` in place of `solution.py`, from the lab folder.

## Setup and type aliases (lines 11 to 27)

```python
FIELDS = ("is_action_item", "owner", "due_date", "priority")

Case = dict[str, Any]  # {"id", "meeting_date", "text", "gold": {field: value}}
Run = dict[str, Any]  # {"system", "model", "test_set_sha256", "predictions": [...]}
Scored = dict[str, Any]  # {"id", "parsed": bool, "fields": {field: 0 or 1}, "exact": 0 or 1}
```

`FIELDS` fixes the four scored fields and their order. `Case`, `Run`, and `Scored` are **type aliases**: new names
for an existing type (here, a dictionary with string keys). They change nothing at run time, but they make
signatures like `score_run(cases: Sequence[Case], run: Run) -> list[Scored]` read like a description of the data,
and the comments record each dictionary's keys. `Sequence` in a type hint means "anything you can index and take
the length of", such as a list or a tuple.

## Loading and helpers: `load_test_set`, `load_run`, `fingerprint`, `percentile` (lines 33 to 57)

```python
def fingerprint(cases: Sequence[Case]) -> str:
    payload = json.dumps([[c["id"], c["text"], c["gold"]] for c in cases], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()

def percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]
```

`load_test_set` and `load_run` read the fixtures. `load_run` refuses a run with no predictions, because an empty run
would otherwise produce divisions by zero deep inside the report.

`fingerprint` (lines 47 to 50) hashes every case's id, input text, and gold labels. A **list comprehension** builds
the list, `json.dumps(..., sort_keys=True)` turns it into canonical text, and SHA-256 reduces it to a 64-character
hex string. Each run records the fingerprint of the test set it was made on. If anyone edits a gold label, adds a
case, or reorders them, the fingerprint changes. Unlike the lab 02 fingerprint, this one is **order-sensitive**: it
hashes the cases in file order, so a reordered test set also counts as different.

`percentile` (lines 53 to 57) uses the **nearest-rank** definition: sort, then take the value at position
`ceil(q / 100 * n)`, counting from 1. `max(1, ...)` keeps `q = 0` from asking for position 0. Worked value from the
test: ten latencies with one 5.0 s outlier give p50 = 0.35 s and p95 = 5.0 s, because `ceil(9.5) = 10`, the slowest
value. That is the honest answer for a tail percentile on ten samples.

## Field scoring: `normalize` and `field_correct` (lines 63 to 77)

```python
def normalize(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().casefold()
    return value

def field_correct(pred: dict[str, Any] | None, gold: dict[str, Any], field: str) -> bool:
    if pred is None or field not in pred:
        return False
    return normalize(pred[field]) == normalize(gold[field])
```

`normalize` treats case and surrounding whitespace as formatting: `"priya "` and `"Priya"` match. Everything that
isn't a string is returned unchanged, so `True`, `None`, and dates stay as they are.

`field_correct` is the per-field rule. The **type hint** `dict[str, Any] | None` says the prediction may be `None`,
which is how the fixtures record an output that didn't parse or failed schema validation. The guard clause makes
both an unparseable output and a missing key **wrong**, not skipped. Gold `None` matches only predicted `None`, so a
model that invents a due date where the meeting gave none is marked wrong, even though the date looks plausible.

## `score_run`, the integrity checks (lines 80 to 103)

```python
    if run.get("test_set_sha256") != fingerprint(cases):
        raise ValueError(f"{run.get('system')}: scored on a different test set (fingerprint mismatch)")
    by_id: dict[str, dict[str, Any]] = {}
    for p in run["predictions"]:
        if p["id"] in by_id:
            raise ValueError(f"{run.get('system')}: duplicate prediction id {p['id']}")
        by_id[p["id"]] = p
    case_ids = [c["id"] for c in cases]
    if set(by_id) != set(case_ids):
        diff = sorted(set(by_id) ^ set(case_ids))
        raise ValueError(...)
    scored = []
    for c in cases:
        out = by_id[c["id"]]["output"]
        fields = {f: int(field_correct(out, c["gold"], f)) for f in FIELDS}
        scored.append({"id": c["id"], "parsed": out is not None, "fields": fields, "exact": int(all(fields.values()))})
```

This is the most important function in the lab, and it is mostly refusals. In order:

1. **Fingerprint.** The run must have been made on exactly this test set. `ft-lora-stale.json` was recorded against
   an older version and is refused. So is any run after someone "fixes" a gold label in place.
2. **Duplicates.** Building `by_id`, a dictionary from id to prediction, catches an id that appears twice. A
   duplicate would otherwise silently replace the earlier prediction.
3. **Exact coverage.** `set(by_id) != set(case_ids)` compares the two id sets. `^` is **symmetric difference**: ids
   in one set but not the other, which the error message samples with `diff[:5]`. This catches a run whose slow or
   failing tail was dropped, which is one of the easiest ways to make a system look better than it is.

Only then does it score, looping over the **test set** (not the predictions), so results come back in test-set
order. The **dictionary comprehension** stores each field as `int(...)`: 1 for correct, 0 for wrong. Integers rather
than booleans make the later averaging and bootstrap arithmetic plain. `exact` is 1 only when `all` four fields are
right, and `parsed` records whether there was an output at all.

Raising `ValueError` instead of printing a warning is the design choice to notice. A benchmark that scores the wrong
thing quietly is worse than one that stops.

## Aggregates: `field_accuracy`, `exact_match`, `parse_rate` (lines 106 to 119)

Each divides by `len(scored)`, the number of test cases, so unparseable outputs count against the system. The
**dictionary comprehension** in `field_accuracy` builds one rate per field. Worked values on the fixtures: the
adapter's exact match is 122 / 150 = 81.3%, the frontier model's 111 / 150 = 74.0%, and the base model's
64 / 150 = 42.7%.

## Intervals: `bootstrap_ci` and `paired_bootstrap_diff` (lines 125 to 154)

```python
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_boot):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return means[int(alpha / 2 * n_boot)], means[int((1 - alpha / 2) * n_boot) - 1]
```

The **bootstrap** estimates how much a score would move if you had drawn a different 150 test cases from the same
population. Each replicate draws `n` cases **with replacement** (`rng.randrange(n)` picks a random index, and the
same index can come up twice), computes the mean, and repeats 2,000 times. The middle 95% of those means is the
interval. With `n_boot = 2000` and `alpha = 0.05`, the bounds are `means[50]` and `means[1949]`.

`_` is the conventional name for a loop variable you don't use. `random.Random(seed)` is a **seeded generator**, so
the same inputs always give the same interval; the docstring spells out the exact procedure so the tests can
reproduce it.

```python
    if len(a) != len(b):
        raise ValueError("paired scores must cover the same cases")
    d = [x - y for x, y in zip(a, b)]
    lo, hi = bootstrap_ci(d, n_boot=n_boot, alpha=alpha, seed=seed)
```

`paired_bootstrap_diff` answers the real question: is system A better than system B **on the same cases**? It
first computes the per-case difference (each is -1, 0, or +1 for exact match), then bootstraps the mean of those
differences. Resampling differences means both systems are always resampled on the same case indices. That removes
the shared difficulty of each case (a hard case is hard for both), so the paired interval is narrower than comparing
two separate intervals. A test checks exactly that.

The length check raises before `zip` can quietly truncate the longer list. Worked value: the adapter versus the
frontier model is +7.3 points with an interval of about [+0.0, +15.3]. The defensible claim is "no worse, and
plausibly better, on this test set", not "beats the frontier model".

## Cost and latency (lines 160 to 193)

```python
    total = sum(p["input_tokens"] * usd_per_mtok_in + p["output_tokens"] * usd_per_mtok_out for p in preds) / 1e6
    return total / len(preds) * 1000

    if not 0 < utilization <= 1:
        raise ValueError("utilization must be in (0, 1]")
    return gpu_hourly_usd / (tasks_per_hour * utilization) * 1000
```

`api_cost_per_1000` (lines 160 to 164) uses the **recorded** token counts for each prediction, not an assumed
average, and prices them at per-million-token rates.

`selfhost_cost_per_1000` (lines 167 to 177) models a rented GPU you pay for every hour, of which only
`utilization` does useful work. `0 < utilization <= 1` is a **chained comparison**, Python's readable way to write
"between 0 (exclusive) and 1 (inclusive)". Worked value: $0.80 an hour at 3,000 tasks an hour is about $0.27 per
1,000 when the GPU is always busy, and five times that, $1.33, at the recorded 20% utilization. Idle hours still
cost money, which is why utilization, not raw throughput, usually decides self-hosted cost.

`cost_per_1000` (lines 180 to 187) **dispatches** on the `"kind"` in `costs.json` and raises for anything else
(`{kind!r}` in the f-string shows the value with quotes, so an empty string or `None` is visible in the message).
`cost_spec.get("utilization", 1.0)` defaults to a fully busy GPU when the field is missing, which is the optimistic
assumption; a reviewer might prefer it to be required.

`latency_summary` (lines 190 to 193) reports p50 and p95 with the nearest-rank `percentile`.

## The report: `summarize` and `render_report` (lines 199 to 269)

`summarize` (lines 199 to 223) is provided and ties everything together. It scores every run (so every integrity
check runs before any number is computed), checks that the reference system is present, builds one row per system,
and adds `vs_reference`, the paired difference in exact match, for every non-reference system. Each row also
records the model and prompt version, so the report says exactly what was compared.

`render_report` (lines 226 to 269) builds a list of lines and joins them with `"\n"` at the end. The **f-string format
specifications** do the work: `{100 * r['exact']:.1f}%` is a percentage with one decimal, `${r['cost_per_1000']:.2f}`
is dollars and cents, and `{100 * v['diff']:+.1f}` always shows a sign, so "+7.3" and "-31.3" can't be misread. The
table header is built with `" | ".join(FIELDS)`, so adding a field updates the header automatically.

The closing lines (264 to 268) say what the intervals do **not** cover: run-to-run variation, prompt choices, and
traffic that differs from the test set. That sentence is part of the result, and a test requires it.

## The CLI: `main` (lines 272 to 292)

`main` reads the arguments with `argparse` (`nargs="+"` means one or more run files), loads everything, prints the
report, and optionally writes it to a file. It takes `argv` as a parameter, defaulting to the real command line, so
the test can call `main([...])` directly. `sys.exit(main())` passes the return code to the shell.

## What the tests check

- **Field scoring** (`test_normalize_strings_only`, `test_field_correct_*`): formatting differences are forgiven;
  wrong values, invented dates, missing keys, and unparseable outputs are wrong; null matches null.
- **Integrity** (`test_score_run_*`): failures stay in the denominator and results keep test-set order; a stale run,
  an edited gold label, a duplicate id, and a truncated run are all refused.
- **Aggregates and headline numbers** (`test_aggregate_metrics_on_a_tiny_example`, `test_fixture_headline_numbers`):
  the three rates on a hand-checkable example, and the fixture's exact-match counts and per-field story.
- **Intervals** (`test_bootstrap_*`, `test_paired_difference`, `test_pairing_narrows_the_interval`): the procedure
  matches the docstring exactly, the interval behaves sensibly (narrower with more data), the paired difference is
  computed on the same indices, and pairing beats unpaired resampling.
- **Cost and latency** (`test_api_cost_per_1000` through `test_latency_summary`): API pricing from token counts,
  utilization's effect, input validation, dispatch, and nearest-rank percentiles.
- **Report and CLI** (`test_report`, `test_cli_writes_report`): the required lines and formats, no self-comparison,
  the caveat sentence, and the file written by the CLI.

What they don't cover: whether 150 cases are representative of production traffic, run-to-run variation (each
system has one run), per-field intervals (only exact match gets a paired comparison; CHANGE.md adds per-field ones),
and the realism of the costs, which are a dated snapshot.

## Review questions

1. An AI assistant changes `score_run` to skip predictions whose id isn't in the test set and to score only the
   cases that have predictions, "so a partial run can still be reported". What is wrong with that?

   <details><summary>Answer</summary>

   The cases most likely to be missing are the slow or failing ones, so the system's score goes up exactly when it
   should go down. Dropped cases also break pairing, because the systems are no longer scored on the same cases. The
   test that truncates the frontier run's last five predictions exists to catch this.

   </details>

2. Why is the paired interval for ft-lora versus frontier narrower than what you'd get by comparing their two
   separate exact-match intervals?

   <details><summary>Answer</summary>

   Many cases are easy or hard for both systems. Resampling per-case differences keeps each case's two scores
   together, so the shared difficulty cancels out and only the disagreements vary. Separate intervals treat the two
   systems as independent and double-count that variation.

   </details>

3. The adapter's exact match is 81.3% and the frontier model's is 74.0%. A stakeholder wants the slide to say "our
   model beats the frontier model". What would you write instead, and why?

   <details><summary>Answer</summary>

   Something like "on this 150-case test set, the adapter is no worse than the frontier model and plausibly better:
   +7.3 points, 95% paired interval about 0 to +15". The interval's lower end touches zero, the test set is small and
   synthetic here, and the intervals don't cover run-to-run variation or production traffic.

   </details>

4. `costs.json` gives the adapter 20% utilization. What happens to its cost per 1,000 tasks at 100% and at 5%, and
   what does that tell you?

   <details><summary>Answer</summary>

   About $0.27 at 100% and about $5.33 at 5% (from $1.33 at 20%). The API's $1.94 doesn't move with your traffic. So
   the self-hosting decision depends on keeping the GPU busy, which is a property of your traffic, not of the model.
   Lesson 11 turns this into a break-even volume.

   </details>
