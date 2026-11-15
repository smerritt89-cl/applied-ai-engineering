# Change: one bad call must not crash a judge run

## The change

`run_judge` makes one API call per example. Right now, if any single call goes wrong in a way `judge` doesn't expect, the whole run stops with a traceback and you lose every verdict already collected. Two cases are unhandled:

1. The reply finishes normally, but `response.parsed_output` is `None`. The last line of `judge` then raises `AttributeError`.
2. The API call itself raises an exception from the SDK (a dropped connection, an overloaded server, a rate limit). These all inherit from `anthropic.APIError`.

Change `judge` so that neither case raises:

- `parsed_output` is `None` after a normal stop: return status `"invalid"`, verdict `None`.
- The call raises `anthropic.APIError`: return status `"error"`, verdict `None`, and put the exception's text (`str(err)`) in `critique` so you can see what went wrong.
- Any other exception (a `TypeError` from a bug in your own code, for example) must still raise. Catching everything would hide real bugs.

Add the two new values to the `status` type hint on `JudgeResult`, and update `judge`'s docstring to list every status. Nothing else changes: `score_judge` already counts a `None` verdict as an error and never as a fail, which is exactly why returning `None` is safe.

You make the change in `work.py` (your copy of the solution), not in `solution.py`.

## Write your prompt

Write your own prompt for a coding assistant before you open the example. A good prompt here:

- Names the file and the one function to change (`judge` in `work.py`), plus the `JudgeResult` type hint.
- Lists each case and the exact status string, verdict, and critique it should produce.
- Names the exception class to catch (`anthropic.APIError`) and says explicitly not to catch bare `Exception`.
- Says what must not change: the call arguments, the refusal and truncation handling, `score_judge`, `run_judge`.
- Asks for tests that use a fake client (no network, no API key), including one where a later call still runs after an earlier one fails.

## Example prompt

<details>
<summary>Show the example prompt</summary>

```text
In studio-3/02-judge-calibration/work.py, make judge() robust so one bad call can't crash run_judge.

Change only judge() and the status type hint on JudgeResult:
- Wrap the client.messages.parse(...) call in try/except anthropic.APIError as err and return
  JudgeResult(example.id, None, str(err), "error"). Catch only anthropic.APIError, not Exception:
  programming errors such as TypeError must still raise.
- After the existing refusal and max_tokens checks, if response.parsed_output is None return
  JudgeResult(example.id, None, "", "invalid").
- Add "invalid" and "error" to the Literal on JudgeResult.status.
- Expand judge()'s docstring to list every status and say that non-ok results have verdict None.

Keep the parse() arguments exactly as they are (no temperature, same output_config), keep the
refusal and truncated handling, and don't change score_judge, run_judge, or main.

Add offline tests with a fake client whose parse() returns or raises scripted items:
parsed_output None gives "invalid"; anthropic.APIConnectionError gives "error" with the message in
critique; TypeError still raises; and run_judge over three examples (ok, error, invalid) makes all
three calls and score_judge reports errors == 2. Then run the lab's tests and show me the output.
```

</details>

## Review the AI's change

Before you accept it, read the diff and check:

- **Narrow catch.** It catches `anthropic.APIError`, not `Exception` or a bare `except:`. A broad catch would turn a typo in your own code into a quiet `"error"` status on every example, and the run would look like the API was down.
- **No silent fail.** Every new path returns `verdict=None`. A version that returns `"fail"` for errors would inflate TNR, the exact bias `score_judge` was designed to avoid.
- **Call unchanged.** The `parse()` arguments are identical: same `output_format`, same `output_config`, no sampling parameters added, no retries or model fallback slipped in. A fallback to another model would mean some verdicts came from a different judge than the one you calibrated.
- **Order of checks.** `stop_reason` is still checked before `parsed_output` is read, so refusals and truncations keep their own statuses.
- **Tests are offline.** The new tests use a fake client and build the SDK exception directly. No network, no key.
- **Docs.** The docstring and the `Literal` list every status the function can return.

## Check it

From the `labs` folder:

```bash
pytest studio-3/02-judge-calibration/test_change.py -q
```

Then run the full lab tests to make sure nothing else broke:

```bash
pytest studio-3/02-judge-calibration -q
```

If you run the live judge afterwards, look at the `errors` count in the report line. A nonzero count is no longer a crash, so it is now your job to notice it.
