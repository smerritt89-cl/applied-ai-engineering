# Change: log every retry

You'll make this change in `work.py` (your copy of `solution.py`), using a coding assistant
such as Claude Code. Then you'll review what it did before running the acceptance tests.

## The change

`with_retries` retries silently. When a batch job is slow, you can't tell whether the API was
overloaded, rate limited, or dropping connections, or how long you spent waiting. The lesson
names "logging of each attempt" as one of the few good reasons to write your own retry wrapper
instead of relying on the SDK's.

Add an optional `on_retry` keyword argument to `with_retries`. When given, it is a function
called as `on_retry(attempt, exc, delay)` **just before each sleep**:

- `attempt` is the 0-based attempt that just failed,
- `exc` is the exception that caused the retry,
- `delay` is the number of seconds about to be slept (the same number passed to `sleep`).

It must **not** be called when the first attempt succeeds, when an error isn't retryable (a
400 is still raised immediately), or after the last attempt (that failure is raised, not
retried). With `on_retry` left out, `with_retries` must behave exactly as it does now.

Your `__main__` block could then pass something like
`on_retry=lambda a, e, d: print(f"attempt {a} failed ({type(e).__name__}), waiting {d:.1f}s")`.

## Write your prompt

Write your own prompt first, before you open the example. A good one for this change:

- Names the function (`with_retries`) and the exact callback signature, argument order
  included.
- Says **when** it is called (before each sleep) and when it is not (success, non-retryable
  errors, the final attempt).
- Pins down that `delay` must be the value actually slept, computed once, so the log can't
  disagree with reality.
- Says it must be keyword-only with a default of `None`, so existing calls don't change.
- Says what must not change: `is_retryable`, `backoff_delay`, the retry rules, and the bare
  `raise` that preserves the original exception.
- Asks for the docstring to be updated, and for tests using a fake `sleep` and fixed `rng`.

<details>
<summary>Example prompt</summary>

```text
In work.py, add an optional keyword-only parameter to with_retries:
    on_retry: Callable[[int, BaseException, float], None] | None = None

When it is not None, call on_retry(attempt, exc, delay) once per retry, just
before sleeping, where attempt is the 0-based attempt that failed, exc is the
exception it raised, and delay is the backoff delay about to be slept. Compute
the delay once, store it in a variable, and pass that same value to both
on_retry and sleep.

Do not call on_retry when fn succeeds, when the error is not retryable, or
after the last attempt; those paths must still raise the original exception
with a bare `raise`. Don't change is_retryable, backoff_delay, the retry
conditions, or anything else in the file. With on_retry omitted, behavior must
be identical to now.

Update the with_retries docstring to describe on_retry. Add tests with a fake
sleep (sleeps.append) and rng=lambda: 1.0 covering: two transient failures
then success (callback gets attempts 0 and 1 with delays 0.5 and 1.0), a 429
with retry-after "5" (delay reported as 5.0), a 400 (callback never called),
and max_attempts=3 all failing (callback called twice, not three times).
```

</details>

## Review the AI's change

Read the diff before running anything. Check:

- [ ] **Scope.** Only `with_retries` (its signature, docstring, and loop body) changed. No edits
  to `is_retryable`, `backoff_delay`, `_retry_after_seconds`, or the other functions.
- [ ] **Backward compatible.** The new parameter comes after the `*` (keyword-only) and
  defaults to `None`, and the code checks `if on_retry is not None` before calling it.
- [ ] **One delay.** The delay is computed once and the same value goes to `on_retry` and
  `sleep`. Watch for `backoff_delay(...)` being called twice: with real jitter, the logged and
  slept delays would then differ.
- [ ] **Placement.** The callback runs after the "should we give up?" check and before
  `sleep`. If it sits above the check, it fires on the final failure and on 400s too.
- [ ] **Errors still surface.** The bare `raise` is untouched, so callers still get the
  original exception type. No new `try`/`except` around the callback that swallows errors.
- [ ] **Docs and tests.** The docstring explains the callback and when it fires, and the
  assistant's tests cover the not-called cases, not just the happy path.

## Check it

From the `labs` folder:

```bash
pytest studio-1/01-first-call/test_change.py -q
pytest studio-1/01-first-call -q
```

The first command runs the acceptance tests for this change. The second runs the whole lab, to
make sure nothing else broke. (`change_solution.py` has a reference version if you want to
compare after you've reviewed your own.)

Stretch (needs an API key): pass a printing `on_retry` in the `__main__` block and run
`python studio-1/01-first-call/work.py`. On a healthy day you'll see no retries at all, which
is also worth knowing.
