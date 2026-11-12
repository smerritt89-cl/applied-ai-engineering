# Lab 03 (Studio 3): Compare two systems and gate a release

**Goes with:** Studio 3, week 3 (lessons 7 to 9). **Time:** about 60 minutes. **Needs:** the shared lab setup
(`labs/README.md`). No API key: everything runs on recorded results.

## Goal

A teammate wants to replace the support-triage system's model and prompt. You have one recorded eval run of each
system on the same 240 questions. Turn those two files into a decision you could defend in a review:

1. Pass rates with **Wilson** intervals and **cluster-bootstrap** intervals (the questions come in groups of four
   per help-center article, so they are not independent).
2. The **paired difference** between the systems with its interval, and **McNemar's exact test** on the
   disagreements.
3. **Cost per successful task** and p95 latency.
4. A **gate** with a configurable margin: must-pass questions, a paired non-inferiority bound, an optional floor on
   the pass rate, and an optional cost ceiling. The command line exits with code 1 when the gate fails, so CI can
   block a merge on it.

## Files

| File | What it is |
|---|---|
| `fixtures/baseline.json` | Recorded results for the current system (Claude Opus 5.5, prompt `triage-v12`). |
| `fixtures/candidate.json` | The proposed system (Claude Sonnet 5.5, prompt `triage-v13`). |
| `fixtures/candidate_regressed.json` | A worse candidate, to see the gate fail. |
| `fixtures/gate_config.json` | Gate settings: margin, must-pass ids, pass-rate floor, cost ceiling. |
| `fixtures/make_fixtures.py` | Regenerates the fixtures deterministically. The data is synthetic. |
| `eval-gate.example.yml` | An example GitHub Actions workflow (inactive; see below). |
| `starter.py` | Your file. Functions marked `TODO`. The tests import from it. |
| `solution.py` | A reference implementation. Try for 20 minutes first. |

Each result row is `{"id", "cluster", "passed", "cost_usd", "latency_s"}`. Each run file also records the model id,
prompt version, dataset, grader version, and trials per question: the manifest from lesson 8, in miniature.

## Steps

Work in `starter.py`, in this order. Each function's docstring is the spec.

1. `pass_rate` and `wilson_interval`. Check: 164 of 200 gives about (0.761, 0.867); 50 of 50 gives about (0.929, 1.0).
2. `cost_per_success`: total cost of **all** calls divided by passes. Failed calls still cost money.
3. `cluster_bootstrap_ci`: resample whole clusters with replacement and apply a statistic. Use
   `random.Random(seed)` and the percentile positions in the docstring so results are reproducible.
4. `align`: pair the two runs by question id. Refuse to compare runs that cover different questions, contain
   duplicates, or disagree about a question's cluster. Silent misalignment is the most common way a comparison lies.
5. `paired_difference` and `mcnemar_exact`.
6. `gate`. The order of checks matters: must-pass cases first, then the paired bound, then the optional floor and
   cost ceiling.

Run the tests until they pass:

```bash
cd labs && source .venv/bin/activate
pytest studio-3/03-compare-and-gate -q
```

Then run the gate:

```bash
cd studio-3/03-compare-and-gate
python starter.py fixtures/baseline.json fixtures/candidate.json --config fixtures/gate_config.json
python starter.py fixtures/baseline.json fixtures/candidate_regressed.json --config fixtures/gate_config.json; echo "exit $?"
python starter.py fixtures/baseline.json fixtures/candidate.json --config fixtures/gate_config.json --margin 0.0
```

## What to notice

- **The candidate is cheaper, not proven better.** It passes 210 against 204, a 2.5-point gain, but the paired
  interval runs from about minus 1 to plus 6 points and McNemar's exact p is about 0.24. At half the cost per success
  and lower latency, it still passes a non-inferiority gate with a 3-point margin. That is the honest claim: "no
  detectable loss, at half the cost," not "better."
- **Clustering moves the intervals.** Compare each system's Wilson interval with its cluster-bootstrap interval, and
  the paired interval with the cluster version on the same line. The candidate's gains came partly from fixing two
  whole articles, so the honest paired interval is wider. Set `"cluster_bootstrap": true` in the config with a
  margin of 0.015 and watch the gate change its verdict.
- **A zero margin is a coin flip.** With `--margin 0.0` the gate demands a lower bound above zero, which this eval is
  too small to deliver. Choose the margin and the suite size together (lesson 8), and write both down before you run.
- **Must-pass cases are separate from averages.** Flip `q050` to failed in a copy of the candidate and the gate fails
  even though the average barely moves.

## CI example

`eval-gate.example.yml` shows the two tiers from lesson 8: an offline job that runs these tests and the gate on
recorded results for every push and pull request, and a scheduled job that runs a live, uncached suite with an API
key from repository secrets and gates the fresh results against the stored baseline. It lives here rather than in
`.github/workflows/`, so it documents the pattern without running on this repository. To adopt it, copy this lab's
`solution.py` (or your `starter.py`) into your project as `evals/compare_gate.py`, write a `run_suite.py` that records
results in the same JSON shape, and copy the workflow to `.github/workflows/`.

If you run several trials per question, store each question's mean score instead of a single `passed` value, and
compute the paired statistics on those per-question means. Don't add each trial as a separate row: repeated trials
of one question are not independent questions (lesson 7).

## Expected cost

Free. Nothing in this lab calls an API. The example workflow's nightly job would; its cost depends on your suite.
