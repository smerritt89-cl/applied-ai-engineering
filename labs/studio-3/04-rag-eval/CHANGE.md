# Change: record a judge failure instead of crashing the run

## The change

`judge_claim` raises `JudgeFailed` when the live judge refuses, runs out of tokens, or returns nothing that parses.
That is the right behavior for one call. But `evaluate` doesn't catch it, so on a `--live` run of a few hundred
claims, one refusal stops everything and you get no report at all. The README already says a production judge should
handle refusals and log how often they happen.

Change `evaluate` so a judge failure on one answer is recorded, not fatal:

- If judging any claim of a case raises `JudgeFailed`, that case gets `None` in `per_case` (not scored, like an
  abstention, but **not** counted as an abstention), and its id is added to a new list,
  `summary["faithfulness"]["judge_failed"]`, in case order. With no failures the list is empty.
- The judge-agreement check skips failed cases, so it doesn't call the judge for them again.
- Only `JudgeFailed` is caught. Any other exception (a bug, a `KeyError` from the recorded judge) must still stop the
  run.
- `build_report` adds one line to the Faithfulness section: `Judge failures: q7 (excluded from the mean).`, or
  `Judge failures: none (excluded from the mean).` when there are none.

The work happens in `work.py` (your copy of the solution). Ask a coding assistant to make the change there.

## Write your prompt

Write your own prompt before you open the example. A good prompt for this change:

- Names the functions (`evaluate` and `build_report` in `work.py`) and the exception to catch, by name.
- Says exactly what a failed case looks like in the summary (the `None`, the new key and its name, the order).
- Says what must **not** be caught (anything other than `JudgeFailed`) and what must not change (`faithfulness`,
  `judge_claim`, the other report sections, the existing summary keys).
- Covers the second place the judge is called (the agreement loop), which is easy to forget.
- Asks for tests, including one that a non-`JudgeFailed` error still raises.

## Example prompt

<details>
<summary>Show the example prompt</summary>

```text
In work.py, make evaluate() tolerate a judge failure on individual answers.

1. Replace the per_case dict comprehension with a loop. For each case, call faithfulness() inside
   try/except JudgeFailed. On JudgeFailed, set per_case[case_id] = None and append the case id to a list
   judge_failed. Catch only JudgeFailed; any other exception must propagate.
2. Add "judge_failed": judge_failed to summary["faithfulness"]. Do not change n_abstained: a judge failure
   is not an abstention.
3. In the human-label agreement loop, skip cases whose id is in judge_failed, the same way abstentions are skipped.
4. In build_report, in the Faithfulness section right after the "Judge:" line, add
   f"Judge failures: {', '.join(f['judge_failed']) or 'none'} (excluded from the mean)."
5. Update the docstrings of evaluate and build_report to mention this.

Do not change faithfulness(), judge_claim(), the judges, the other report sections, or any existing summary key.

Add tests using a judge that wraps RecordedJudge and raises JudgeFailed for every claim of q7: the run completes,
judge_failed == ["q7"], per_case["q7"] is None, n_scored == 6, n_abstained == 1, judge agreement n == 13, and the
report says "Judge failures: q7". Also test that a clean run gives judge_failed == [] and the report says
"Judge failures: none", and that a KeyError from the judge still raises.
```

</details>

## Review the AI's change

Before you accept it, read the diff and check:

- [ ] **Narrow catch.** The `except` names `JudgeFailed`. A bare `except:` or `except Exception:` would also swallow
      real bugs, such as a `split_claims` mismatch with the recorded judgments, and turn them into "judge failures".
- [ ] **Failures are not abstentions.** `n_abstained` still counts only `abstained` cases. Mixing the two would hide
      how often the judge breaks.
- [ ] **The agreement loop skips failed cases.** Otherwise it calls the judge again for the same claims (paying twice on
      a live run) and can raise the same `JudgeFailed` outside the `try`.
- [ ] **No silent default.** A failed case is `None` and listed, never scored as 0.0 or 1.0.
- [ ] **Scope.** `faithfulness`, `judge_claim`, both judge classes, and the other report sections are unchanged, and the
      bottom line is still short (an existing test limits it to about 120 words).
- [ ] **Tests.** New tests cover a failure, a clean run, the report line, and an unrelated exception still raising.
      The existing tests still pass.

## Check it

From the `labs` folder:

```bash
pytest studio-3/04-rag-eval/test_change.py -q
```

These tests fail until the change is made. Then run the full lab to make sure nothing else broke:

```bash
pytest studio-3/04-rag-eval -q
```

All of these are offline. They use a fake judge that raises `JudgeFailed` on purpose, so no API key is needed.
