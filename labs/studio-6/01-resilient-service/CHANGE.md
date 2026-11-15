# Change: don't blame the fallback for a deadline it never got

You'll make this change in `work.py` (your copy of `solution.py`), using a coding assistant
such as Claude Code. Then you'll review what it did before running the acceptance tests.

## The change

This is a bug fix. When the primary model is slow (each attempt hangs until its timeout), it can
use up the request's whole deadline. The chain then moves on to the fallback, and
`call_with_retries` raises `DeadlineExceeded` before calling it. Because `DeadlineExceeded` is a
subclass of `TransientError`, `complete` and `stream_events` treat that as the fallback failing
and call `breaker.record_failure()` on it.

The effect in production: during a slow Opus outage, every request records a failure against
Sonnet, which was never even called. After a few requests Sonnet's breaker opens, so the service
loses its fallback exactly when it needs it.

There is a second, quieter version of the same bug. If the fallback's breaker was half-open,
`allow()` handed this request the single trial call. No call happens, but the trial slot is
never given back, so the breaker reopens (and in other designs, sticks).

You want:

- When `DeadlineExceeded` is raised for a model, **don't** record a failure (or a success) on its
  breaker. Add a note like `"claude-sonnet-5-5: skipped, deadline exhausted"`, and stop trying
  further models, since they would have no time either. The request then degrades as before.
- If `allow()` had handed out a half-open trial for that model, give the trial back, so the next
  request can use it.
- The same in both `complete` and `stream_events`.

Real failures must still count: the primary, which did hang and fail, still gets
`record_failure()`.

## Write your prompt

Write your own prompt first, before you open the example. A good one for this change:

- States the bug in one or two sentences, including *why* the current code does it (the
  subclass relationship and the order of the `except` clauses).
- Names both methods that need the fix.
- Says what should happen instead: no breaker update, a note, stop the chain, degrade.
- Covers the half-open trial, and suggests how to release it (a small method on
  `CircuitBreaker` is cleaner than reaching into `trial_in_flight` from outside).
- Says what must not change: real transient failures still count, refusals and permanent errors
  behave as before, and `DeadlineExceeded` stays a subclass of `TransientError` (other code relies
  on that).
- Asks for tests that use a fake clock and a client that hangs.

<details>
<summary>Example prompt</summary>

```text
In work.py there's a bug in ResilientLLM.complete and ResilientLLM.stream_events.
When the primary model uses up the whole request deadline, the loop moves on to
the fallback, call_with_retries raises DeadlineExceeded before calling it, and
because DeadlineExceeded subclasses TransientError, the `except TransientError`
branch calls breaker.record_failure() on a model that was never called. That can
open a healthy fallback's breaker during a slow primary outage.

Fix it in both methods: add an `except DeadlineExceeded` clause before the
`except TransientError` clause. In it, don't record success or failure on the
breaker; append the note f"{model}: skipped, deadline exhausted"; and break out
of the model loop so the request degrades exactly as it does now.

Also handle the half-open case: if allow() gave this request the half-open
trial, the trial must be released so the next request can use it. Add a small
CircuitBreaker.release_trial() method that sets trial_in_flight = False, and
call it in the new branch.

Don't change call_with_retries, the exception hierarchy (DeadlineExceeded must
stay a TransientError subclass), or the handling of Refused, PermanentError, or
real TransientErrors. The primary, which really did fail, must still get
record_failure().

Add tests with a fake clock and a client whose primary advances the clock by
the timeout and raises TransientError: the fallback is never called and its
breaker has 0 failures; the note is present; the same for stream_events; and a
half-open fallback breaker is still half-open, with allow() returning True,
after the request.
```

</details>

## Review the AI's change

Read the diff before running anything. Check:

- [ ] **Clause order.** The new `except DeadlineExceeded` comes **before** `except
  TransientError` in both methods. Python uses the first matching clause, so if it comes after,
  it never runs.
- [ ] **Both methods.** `stream_events` has its own copy of the chain; a fix in `complete` alone
  passes half the tests.
- [ ] **Real failures still count.** The primary's breaker still records its failure. Watch for a
  "fix" that stops recording failures for any timeout, which would stop the breaker from ever
  opening on a hung model.
- [ ] **The trial is released.** If the model's breaker was half-open, the trial flag is cleared
  without reopening the breaker or resetting its failure count. Calling `record_success()` here
  would be wrong: it would close the breaker without any evidence the model works.
- [ ] **Scope.** `call_with_retries`, `classify_exception`, and the exception classes are
  untouched. Changing `DeadlineExceeded` to stop inheriting from `TransientError` "fixes" this
  test but changes behavior everywhere else that catches `TransientError`.
- [ ] **Notes and degradation.** The degraded reply (or `degraded` event) still comes back, and
  its notes say why the fallback was skipped.

## Check it

From the `labs` folder:

```bash
pytest studio-6/01-resilient-service/test_change.py -q
pytest studio-6/01-resilient-service -q
```

The first command runs the acceptance tests for this change. The second runs the whole lab, to
make sure nothing else broke. (`change_solution.py` has a reference version if you want to
compare after you've reviewed your own.)
