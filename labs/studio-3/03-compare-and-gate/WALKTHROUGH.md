# Walkthrough: comparing two systems and gating a release

## What this code does

`solution.py` reads two recorded eval runs, a **baseline** (the system in production) and a **candidate** (the proposed
replacement), scored on the same 240 support-triage questions. It turns them into a release decision you could defend
in a review: pass rates with honest intervals, the paired difference between the two systems, a significance test on
the questions where they disagree, cost per successful task, p95 latency, and finally a **gate** that says PASS or FAIL
with reasons.

The whole file is standard library only: `json`, `math`, `random`, `argparse`. No API calls, no numpy. That is a
deliberate choice for a CI gate: it runs anywhere, in under a second, and gives the same answer every time.

The file reads top to bottom in the same order you would reason about the problem: statistics for **one system**,
then statistics for **two systems side by side**, then **the gate** that combines them, then the report and the
command line.

## How to read this lab

Open `work.py` beside this page. It starts as a copy of `solution.py`, so the line numbers below match it until you
change something. Run the tests from VS Code's **Testing** panel (the flask icon): expand `studio-3`, then
`03-compare-and-gate`, and press the run button. They should all pass. When a section below mentions a test, find it
in `test_compare_gate.py` and read it next to the code it checks.

You can also run the gate yourself from a terminal in this folder:

```bash
python work.py fixtures/baseline.json fixtures/candidate.json --config fixtures/gate_config.json
```

## The header and type aliases (lines 1 to 22)

```python
from __future__ import annotations
...
Result = dict[str, Any]  # {"id", "cluster", "passed", "cost_usd", "latency_s"}
Pair = dict[str, Any]  # {"id", "cluster", "base": 0 or 1, "cand": 0 or 1}
```

The module docstring (lines 1 to 8) says what the file does and how to run it. `from __future__ import annotations`
(line 9) tells Python not to evaluate type hints at definition time, which lets the file use modern hint syntax such as
`str | pathlib.Path` on older Python versions.

Lines 21 and 22 are **type aliases**: `Result` and `Pair` are just new names for `dict[str, Any]`, a dictionary with
string keys and values of any type. They change nothing at run time. They exist for the reader: a signature that says
`align(base: Sequence[Result], ...) -> list[Pair]` tells you what goes in and what comes out, and the trailing comments
spell out the keys. When you review AI-written code, aliases like these are a good sign; a file full of bare `dict`
and `list` hints makes you reverse-engineer the data shape from the code.

## `load_run` (lines 28 to 33)

```python
data = json.loads(pathlib.Path(path).read_text())
if not data.get("results"):
    raise ValueError(f"{path}: no results")
```

`pathlib.Path(path).read_text()` reads the whole file as a string, and `json.loads` turns it into Python dictionaries
and lists. `data.get("results")` is **dict.get**: it returns the value if the key exists and `None` if it doesn't,
instead of raising `KeyError`. `not` treats both `None` and an empty list as "nothing here", so one check covers a
missing key and an empty run.

Why check at all? A gate that silently compares against an empty file would divide by zero later with a confusing
message, or worse, pass. Failing at load time with the file name in the message (an **f-string**, `f"{path}: ..."`)
points straight at the problem.

## `pass_rate` (lines 39 to 41)

```python
return sum(1 for r in results if r["passed"]) / len(results)
```

`sum(1 for r in results if r["passed"])` is a **generator expression**: like a list comprehension in parentheses, it
yields a 1 for each passing result without building a list, and `sum` adds them up. Dividing by `len(results)` gives
the fraction. The baseline fixture passes 204 of 240, so this returns 0.85.

## `wilson_interval` (lines 44 to 52)

```python
p = k / n
denom = 1 + z * z / n
center = (p + z * z / (2 * n)) / denom
half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
return max(0.0, center - half), min(1.0, center + half)
```

This is the Wilson score interval from lesson 7, transcribed term by term. `z = 1.96` is a **default argument**: the
z value for a 95% interval, which a caller can override. For 164 passes out of 200 it returns about (0.761, 0.867).

Why Wilson and not the textbook "p plus or minus 1.96 standard errors" (the Wald interval)? Wald breaks at the edges.
For 50 of 50 it gives zero width, claiming certainty from 50 questions; for 48 of 50 its upper bound goes above 1.
Wilson pulls the center toward one half and stays sensible, giving about (0.929, 1.0) for 50 of 50. The tests include
both of those cases with comments, because they are exactly where a "simpler" AI rewrite would quietly go wrong.

Two details to check in review. The `n <= 0` guard (lines 46 and 47) raises a `ValueError` with a clear message
instead of a `ZeroDivisionError`. The `max(0.0, ...)` and `min(1.0, ...)` clip guards against tiny floating point
overshoot, so a rate interval never prints as 1.0000000002.

## `cluster_bootstrap_ci` (lines 55 to 81)

```python
groups: dict[str, list[dict[str, Any]]] = {}
for item in items:
    groups.setdefault(item["cluster"], []).append(item)
clusters = list(groups.values())
rng = random.Random(seed)
values = []
for _ in range(n_boot):
    sample: list[dict[str, Any]] = []
    for _ in range(len(clusters)):
        sample.extend(clusters[rng.randrange(len(clusters))])
    values.append(stat(sample))
values.sort()
return values[int(alpha / 2 * n_boot)], values[int((1 - alpha / 2) * n_boot) - 1]
```

The questions come in groups of four per help-center article. Questions about the same article tend to pass or fail
together, so 240 questions carry less independent evidence than 240 coin flips. The **cluster bootstrap** respects
that: it resamples whole articles, not single questions.

How it is built:

- Lines 69 to 71 group items by cluster. `dict.setdefault(key, [])` returns the list already stored under `key`, or
  stores and returns a new empty list if there isn't one, so `.append(item)` always has a list to append to. Python
  dictionaries keep insertion order, which is why the docstring can promise "first-appearance order of clusters".
- Line 73 creates its own random generator, `random.Random(seed)`, instead of using the global `random` module. Same
  seed, same draws, same interval: the test `test_cluster_bootstrap_is_reproducible_and_brackets_the_estimate` checks
  exactly this. A gate whose verdict changes between two runs on the same data is useless in CI.
- Lines 75 to 79 are the resampling loop. `_` is the conventional name for a loop variable you don't use. Each
  replicate draws as many clusters as there are (60 here), with replacement, so some articles appear twice and some
  not at all. `sample.extend(...)` adds all four questions of the drawn article.
- `stat` is a **function passed as an argument** (its type hint, `Callable[[list[...]], float]`, says "a function
  that takes a list and returns a float"). That makes the bootstrap reusable: `summarize` passes `pass_rate`, and
  `cluster_diff_ci` passes a small lambda for the paired difference.
- Line 81 reads the percentiles straight off the sorted list. With the defaults (2000 replicates, alpha 0.05) those
  are `values[50]` and `values[1949]`, the 2.5th and 97.5th percentiles. The exact positions are in the docstring and
  pinned by `test_bootstrap_uses_the_documented_percentile_positions`, so two implementations agree to the digit.

What to check in an AI-written version: that it resamples clusters, not rows (a row-level bootstrap gives an interval
that looks like Wilson and is too narrow); that it uses a seeded `random.Random`; and that the replicate draws
`len(clusters)` clusters, not `len(items)`. The test `test_clustering_widens_the_interval` catches the first mistake.

## `cost_per_success` and `percentile` (lines 84 to 95)

```python
passes = sum(1 for r in results if r["passed"])
total = sum(r["cost_usd"] for r in results)
return total / passes if passes else math.inf
```

Cost per success divides the cost of **every** call by the number of passes. Failed calls still cost money, and a
cheaper model that fails more often can cost more per useful answer. Line 88 is a **conditional expression** (`a if
condition else b`): if there are no passes, return infinity rather than crash, which correctly ranks "never succeeds"
as infinitely expensive.

`percentile` (lines 91 to 95) is the nearest-rank method: sort, then take the value at rank `ceil(q / 100 * n)`. For
240 latencies and q = 95, that is rank 228. `max(1, ...)` keeps the rank at least 1 so `q = 0` doesn't index position
minus 1 (which in Python silently means "the last item").

## `align` (lines 101 to 125)

```python
def index(results: Sequence[Result], name: str) -> dict[str, Result]:
    out: dict[str, Result] = {}
    for r in results:
        if r["id"] in out:
            raise ValueError(f"duplicate id {r['id']} in {name}")
        out[r["id"]] = r
    return out

b, c = index(base, "baseline"), index(cand, "candidate")
if set(b) != set(c):
    missing = sorted(set(b) ^ set(c))
    raise ValueError(f"runs cover different questions, e.g. {missing[:5]}")
```

This is the most important function in the file, even though it computes nothing. A paired comparison only means
something if row 17 of the baseline and row 17 of the candidate are the same question. Pairing by position would
silently produce nonsense if one run was shuffled, had a question dropped, or had one duplicated. `align` pairs by id
and refuses anything suspicious.

- `index` (lines 108 to 114) is a **nested function**: defined inside `align` because nothing else needs it. It builds
  an id-to-result dictionary and raises on a duplicate id, which would otherwise overwrite silently.
- `set(b) != set(c)` compares the two sets of ids (iterating a dict gives its keys). `set(b) ^ set(c)` is the
  **symmetric difference**: ids in one run but not the other. The error shows up to five of them (`missing[:5]` is a
  **slice**), enough to debug without flooding the log.
- Lines 121 to 124 walk the ids in sorted order, raise if a question's cluster differs between runs (which would mean
  the two runs used different versions of the dataset), and build each pair. `int(True)` is 1 and `int(False)` is 0,
  so `base` and `cand` become numbers you can subtract.

Every check here maps to a test in `test_align_rejects_mismatches`. When you review AI-written comparison code, look
for this step first. Code that does `zip(base, cand)` without checking ids is the most common way a comparison lies.

## `paired_difference` (lines 128 to 136)

```python
d = [p["cand"] - p["base"] for p in pairs]
n = len(d)
mean = sum(d) / n
var = sum((x - mean) ** 2 for x in d) / (n - 1)
se = math.sqrt(var / n)
return {"mean": mean, "se": se, "lower": mean - z * se, "upper": mean + z * se}
```

For each question, `d` is plus 1 if only the candidate passed, minus 1 if only the baseline passed, and 0 if they
agree. The mean of `d` is the difference in pass rates. On the fixtures, 12 wins and 6 losses over 240 questions give
a mean of 6 / 240 = 0.025.

The standard error uses the **sample** variance, dividing by `n - 1` (line 134), then `sqrt(var / n)`. For the
fixtures that is about 0.0176, so the interval is 0.025 plus or minus 0.035: about minus 0.010 to plus 0.060. The gain
is not established, which `test_fixture_comparison_numbers` asserts directly.

Why pair at all? The 222 questions where both systems agree contribute zeros, which shrink the variance. Two systems
tested on the same questions are compared much more precisely than two independent samples would be:
`test_pairing_beats_the_unpaired_standard_error` makes that concrete. An AI that "simplifies" this into the difference
of two independent Wilson intervals throws that precision away.

## `mcnemar_exact` (lines 139 to 152)

```python
wins = sum(1 for p in pairs if p["cand"] == 1 and p["base"] == 0)
losses = sum(1 for p in pairs if p["cand"] == 0 and p["base"] == 1)
n = wins + losses
if n == 0:
    return {"wins": 0, "losses": 0, "p": 1.0}
tail = sum(math.comb(n, i) for i in range(min(wins, losses) + 1)) / 2**n
return {"wins": wins, "losses": losses, "p": min(1.0, 2 * tail)}
```

McNemar's test looks only at the **discordant** questions, the ones where the systems disagree. If the two systems
were equally good, each disagreement would be a fair coin flip between "candidate won" and "baseline won". The exact
version computes the binomial tail directly: `math.comb(n, i)` is "n choose i", and summing it for every count at or
below the smaller side, divided by 2 to the n, gives the probability of a split at least this lopsided in one
direction. Doubling makes it two-sided, and `min(1.0, ...)` caps it, because doubling an even split like 3 and 3 would
otherwise exceed 1.

On the fixtures: 12 wins and 6 losses, p of about 0.238. Not significant, consistent with the paired interval
including zero. The `n == 0` early return handles two identical runs, where there is no evidence either way.

## `cluster_diff_ci` (lines 155 to 157)

```python
return cluster_bootstrap_ci(pairs, lambda s: sum(p["cand"] - p["base"] for p in s) / len(s), n_boot=n_boot, seed=seed)
```

This reuses the cluster bootstrap with a different statistic. `lambda s: ...` is a **lambda**: a one-expression
function without a name, here "the mean paired difference of a sample". Because pairs keep their `cluster` key from
`align`, resampling whole articles works on pairs too. On the fixtures this gives about minus 0.021 to plus 0.083,
wider than the plain paired interval, because the candidate's gains are concentrated in two articles.

## `DEFAULT_CONFIG` (lines 163 to 170)

```python
DEFAULT_CONFIG: dict[str, Any] = {
    "margin": 0.03,  # fail if the paired lower bound is below -margin
    "critical_ids": [],  # must-pass questions
    "min_pass_rate": None,  # optional floor on the candidate's Wilson LOWER bound
    "max_cost_ratio": None,  # optional ceiling on candidate / baseline cost per success
    "cluster_bootstrap": False,  # if True, take the lower bound from cluster_diff_ci instead
    "z": 1.96,
}
```

Every gate setting lives in one dictionary at module level, with a comment per key. `None` means "this check is off".
Putting defaults in one place means `gate` never has to guess, and a reviewer can see every knob at a glance. The
margin of 0.03 is a **non-inferiority** margin: the gate accepts a candidate unless the evidence suggests it could be
more than 3 points worse.

## `gate` (lines 173 to 210)

```python
cfg = {**DEFAULT_CONFIG, **(config or {})}
pairs = align(base_run["results"], cand_run["results"])
cand_by_id = {r["id"]: r for r in cand_run["results"]}
reasons: list[str] = []
for qid in cfg["critical_ids"]:
    if qid not in cand_by_id:
        raise ValueError(f"critical id {qid} is not in the results")
    if not cand_by_id[qid]["passed"]:
        reasons.append(f"critical failed: {qid}")
if cfg["cluster_bootstrap"]:
    lower = cluster_diff_ci(pairs)[0]
else:
    lower = paired_difference(pairs, z=cfg["z"])["lower"]
if lower < -cfg["margin"]:
    reasons.append(...)
```

Line 186 merges the caller's settings over the defaults. `{**a, **b}` is **dictionary unpacking**: it builds a new
dict with everything from `a`, then everything from `b`, so keys in `b` win. `config or {}` turns a `None` config into
an empty dict so the unpacking doesn't fail. The caller's dict is not modified.

Line 188 is a **dict comprehension** (`{key: value for ...}`) that indexes the candidate's results by id for the
must-pass lookups.

The checks run in the documented order, and each one appends a human-readable reason rather than returning early:

1. **Must-pass questions** (lines 190 to 194). These are cases you never want to regress, whatever the average does.
   An unknown critical id raises instead of being skipped: a typo in the config should not quietly disable a safety
   check. `test_gate_rejects_unknown_critical_id` pins that.
2. **The paired bound** (lines 195 to 200). Fail if the lower end of the difference interval is below minus the
   margin. The lower bound comes from either the normal approximation or the cluster bootstrap, chosen by config.
3. **The pass-rate floor** (lines 201 to 205): an absolute minimum, checked on the candidate's Wilson **lower** bound,
   not its point estimate, so a small lucky run can't clear it.
4. **The cost ceiling** (lines 206 to 209): candidate cost per success over baseline cost per success.

Collecting every reason (instead of stopping at the first) means one CI run tells you everything that is wrong. Line
210 returns `passed` as `not reasons`: an empty list is falsy, so the gate passes exactly when nothing was flagged.

What to check when an AI edits the gate: that new checks are optional and off by default (so existing configs keep
their meaning), that the order of reasons is preserved (tests check `reasons[0]`), and that `align` still runs before
anything else.

## `summarize` and `format_report` (lines 213 to 255)

These are provided helpers. `summarize` computes every number the report needs, for both systems, in a loop over
`(("baseline", base_run), ("candidate", cand_run))`, a tuple of name and run pairs, so the two systems are always
treated identically. `run.get("model")` uses `dict.get` so a run file without a model id still produces a report.

`format_report` builds a list of lines and joins them with newlines. The format specifiers inside the f-strings do the
presentation work: `:.3f` is three decimals, `:+.3f` forces a sign (so a difference prints as `+0.025` or `-0.010`),
and `{name:9}` pads the name to nine characters so the two system lines align in a terminal.

## `main` (lines 258 to 275)

```python
result = gate(load_run(args.baseline), load_run(args.candidate), config)
print(format_report(result))
return 0 if result["passed"] else 1
...
if __name__ == "__main__":
    sys.exit(main())
```

`argparse` defines the command line: two positional file paths, an optional `--config` file, and an optional
`--margin` override that wins over the config file (lines 267 and 268). `type=float` makes argparse convert and
validate the margin for you.

The return value is the point: 0 when the gate passes and 1 when it fails. `sys.exit(main())` (line 275) hands that to
the operating system, and CI systems treat any nonzero exit code as a failed step. That is how `eval-gate.example.yml`
blocks a merge. `main` takes an optional `argv` list so the tests can call it directly
(`test_cli_exit_codes`) without spawning a process. `if __name__ == "__main__":` runs `main` only when the file is
executed as a script, not when the tests import it.

## What the tests check

- **One system** (`test_pass_rate_on_fixtures`, `test_wilson_known_values`, `test_wilson_rejects_empty`,
  `test_cost_per_success`): exact pass rates on the fixtures, Wilson against known values including the edge cases
  where Wald fails, and that failed calls count toward cost.
- **Bootstrap** (four tests): reproducibility with a seed, agreement with the ordinary bootstrap when every cluster is
  one question, a much wider interval when questions are clustered, and the exact percentile positions.
- **Pairing** (`test_align_*`, `test_paired_difference_known_values`, `test_pairing_beats_the_unpaired_standard_error`,
  `test_mcnemar_exact_known_values`, `test_fixture_comparison_numbers`): alignment by id with every rejection case,
  the paired standard error to six decimals, McNemar's p for six win and loss splits, and the headline fixture result
  (12 wins, 6 losses, p about 0.238, interval including zero).
- **The gate and CLI** (nine tests): pass on the good candidate, fail on the regressed one with the right first reason,
  must-pass failures listed first, unknown critical ids rejected, the margin and cluster options changing the verdict,
  the cost ceiling, defaults without a config, and the CLI exit codes.

What they don't check: the exact wording of reasons beyond their prefixes, the layout of `format_report`, the p95
latency (it is reported but not gated), or whether the runs used the same dataset and grader version. The `dataset`
field is printed but never compared, so a gate between runs on different datasets would happily pass. In a real
pipeline you would want that check too.

## Review questions

1. An AI rewrites `align` as `[{"id": b["id"], ..., "base": int(b["passed"]), "cand": int(c["passed"])} for b, c in zip(base, cand)]`. On the fixtures it still passes `test_gate_passes_the_good_candidate`. What has been lost?

<details>
<summary>Answer</summary>

Every safety check. `zip` pairs by position and stops silently at the shorter list, so a shuffled, truncated, or
duplicated run produces pairs of different questions with no error. The gate's numbers would then describe nothing
real. `test_align_pairs_by_id_and_sorts` (which reverses the candidate) and `test_align_rejects_mismatches` would
both fail, which is why they exist.

</details>

2. Why does the gate check the candidate's Wilson **lower** bound against `min_pass_rate`, rather than its pass rate?

<details>
<summary>Answer</summary>

A floor on the point estimate can be cleared by luck on a small suite. Requiring the lower bound to clear it means
the eval has to show, with 95% confidence, that the true rate is at least the floor. The regressed candidate's lower
bound is about 0.745, below 0.80, so it fails this check.

</details>

3. With `--margin 0.0` the good candidate fails. Is the candidate worse than the baseline?

<details>
<summary>Answer</summary>

No. A zero margin requires the paired lower bound to be above zero, which means proving the candidate is better. The
interval runs from about minus 0.010 to plus 0.060, so the eval can't prove that with 240 questions. The honest claim
is "no detectable loss beyond 3 points, at half the cost per success", not "better". The margin and the suite size
should be chosen together, before the run.

</details>

4. Why does `gate` raise on an unknown critical id instead of skipping it?

<details>
<summary>Answer</summary>

A skipped id is a disabled safety check that nobody notices. If someone renames `q050` in the dataset, or types
`q05O`, a skip would let a regression on that question through. Raising makes the config error visible the first time
the gate runs.

</details>

5. `cluster_bootstrap_ci` uses `random.Random(seed)`. What would go wrong if it called `random.randrange` from the global module instead?

<details>
<summary>Answer</summary>

The interval would change from run to run, and could change when unrelated code also uses the global generator. A gate
near its margin could pass on one CI run and fail on the next with identical data. With a seeded private generator,
the same inputs always give the same interval, which `test_cluster_bootstrap_is_reproducible_and_brackets_the_estimate`
checks.

</details>
