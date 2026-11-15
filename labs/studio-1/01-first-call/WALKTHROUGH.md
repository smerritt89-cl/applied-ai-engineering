# Walkthrough: your first streaming call, cost, and retries

## What this code does

`solution.py` is the small layer that every model call in this studio goes through. It does
four jobs, each in its own function: **stream** a reply from Claude and time it
(`stream_reply`), **price** the call from its token counts (`cost_usd`), **decide** whether the
answer is finished or must be rejected (`require_complete`), and **retry** only the failures
that might succeed a moment later (`is_retryable`, `backoff_delay`, `with_retries`).

Splitting the work this way means each decision lives in exactly one place. If pricing
changes, you edit one function. If a new stop reason appears, you edit one function. It also
means each piece can be tested on its own, without the network: the tests hand these functions
a fake client, a fake clock, and fake errors, and check the results exactly.

The idea worth taking away: **an HTTP 200 is not an answer.** A response can arrive
successfully and still be truncated or a refusal, and a failed request can be either "try
again" or "stop now". This file makes those distinctions explicit, so the rest of your code
doesn't have to.

## How to read this lab

Open `work.py` beside this page. It starts as a copy of `solution.py`, so the line numbers
below match it until you change something. Read a section here, then the code it points to.

Run the tests from VS Code's **Testing** panel (the flask icon): expand
`studio-1/01-first-call` and press the run button. Everything except the two `live` tests runs
without an API key. To see what a failure looks like, change something small in `work.py`
(for example, remove `"stop_sequence"` from line 89), rerun, read the message, then undo it.

## Imports and constants (lines 1 to 21)

```python
from __future__ import annotations

import random
import time
from typing import Any, Callable

import anthropic

DEFAULT_MODEL = "claude-haiku-5-5"  # cheapest current tier: good for a first call

PRICES: dict[str, dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20},
    ...
}

USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
```

`from __future__ import annotations` (line 2) tells Python to keep type hints as text instead
of evaluating them when the file loads. It's a common first line in modern Python files and
has no effect on how the code runs.

The imports are all standard library except `anthropic`, the official SDK. `typing` supplies
two names used in **type hints**, the annotations after a colon or `->` that say what kind of
value is expected: `Any` means "anything", and `Callable[[], float]` means "a function that
takes no arguments and returns a float". Python does not enforce hints at runtime. They are
documentation that editors and checkers can read, and they make AI-written code much easier to
review, because you can see what each function expects without tracing every call.

`PRICES` (lines 14 to 19) is a dictionary of dictionaries: model name, then price per million
tokens for each of the four token kinds. `PRICES: dict[str, dict[str, float]]` is a type hint
on a variable. The comment above it (lines 12 and 13) dates the snapshot and names the source,
and line 17 records a pricing condition (Haiku's rates apply to prompts up to 100,000 tokens).
Any cost figure this code prints is only as current as that date.

`USAGE_FIELDS` (line 21) is a **tuple** (a fixed sequence in parentheses) naming the four
usage counts the API reports. Naming them once means `_usage_dict` and the tests agree on
exactly which fields exist.

## The two exception classes (lines 24 to 29)

```python
class TruncatedError(Exception):
    """The model stopped because it hit a length limit; the text is incomplete."""


class RefusalError(Exception):
    """The model declined to answer (stop_reason == "refusal")."""
```

`class TruncatedError(Exception):` defines a new kind of error by **subclassing** Python's
built-in `Exception`. The body is only a docstring, which is enough: the new class behaves
like any exception, but it has its own name.

Why bother? Because a caller can now catch exactly the case it cares about. A web handler might
catch `TruncatedError` and show "the answer was cut off", catch `RefusalError` and log it for
review, and let everything else surface as a real bug. If both were a generic `Exception` (or,
worse, a returned `None`), the caller couldn't tell them apart. When you review AI-written
code, look for this: distinct failure modes should have distinct, catchable types.

## `_usage_dict` (lines 32 to 33)

```python
def _usage_dict(usage: Any) -> dict[str, int]:
    return {f: int(getattr(usage, f, 0) or 0) for f in USAGE_FIELDS}
```

The SDK returns usage as an object with attributes (`usage.input_tokens`), not a dictionary.
This helper converts it into a plain dict of integers, which is easier to log, compare, and
price.

It's a **dict comprehension**: `{key: value for f in USAGE_FIELDS}` builds a dictionary in one
expression, one entry per field name. `getattr(usage, f, 0)` reads the attribute whose name is
in the string `f`, returning 0 if the attribute doesn't exist at all. Then `or 0` handles the
other case: the attribute exists but is `None`. The tests' fake usage sets
`cache_creation_input_tokens=None`, and `None or 0` is `0`. Without `or 0`, `int(None)` would
raise `TypeError`.

The leading underscore in `_usage_dict` is a Python convention for "internal helper, not part
of this module's public interface".

## `stream_reply` (lines 36 to 72)

```python
def stream_reply(
    client: Any,
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 2048,
    system: str | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
```

The signature (lines 36 to 44) has a bare `*` on line 39. Everything after it is
**keyword-only**: you must write `stream_reply(client, "hi", max_tokens=50)`, never
`stream_reply(client, "hi", "claude-haiku-5-5", 50)`. That prevents a class of silent bugs
where arguments are passed in the wrong order. `system: str | None = None` means "a string,
or `None`", defaulting to `None`.

Two parameters are there for testability. `client` is passed in rather than created inside, so
a test can pass a fake one. `clock` defaults to `time.perf_counter` (a high-resolution timer
meant for measuring durations), and a test passes a fake clock that advances by fixed amounts,
so timing assertions are exact instead of flaky. This is **dependency injection**: hand the
function the things it depends on, instead of having it reach out for them.

```python
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system is not None:
        kwargs["system"] = system
```

Lines 46 to 52 build the request as a dictionary first. `messages` is a list with one user
message. `system` is added only when given (lines 51 and 52), as a top-level field, not as a
message. The tests check both points, and also that no `temperature` is sent: the test file
notes that the current API version rejects sampling parameters, so an AI that "helpfully" adds
`temperature=0.7` breaks the call.

```python
    start = clock()
    ttft = None
    chunks: list[str] = []
    with client.messages.stream(**kwargs) as stream:
        for text in stream.text_stream:
            if ttft is None:
                ttft = clock() - start
            chunks.append(text)
        final = stream.get_final_message()
    total = clock() - start
```

Line 57 does three things. `**kwargs` **unpacks** the dictionary into keyword arguments, so it
is the same as writing `model=model, max_tokens=max_tokens, ...`. `client.messages.stream(...)`
opens a streaming response. And `with ... as stream:` is a **context manager**: Python
guarantees the stream is closed when the block ends, even if an exception is raised partway
through. Without `with`, an error mid-stream could leave the connection open.

`stream.text_stream` (line 58) yields the reply's text in chunks as they arrive. Lines 59 and
60 record **time to first token** (TTFT) the first time through the loop only, since `ttft` is
`None` until then. Each chunk is appended to a list (line 61), and the list is joined once at
the end, which is the usual Python pattern for building a long string from pieces.

After the loop, `stream.get_final_message()` (line 62) returns the complete message, which is
where `stop_reason` and `usage` live. `total` (line 63) is measured after that, so it includes
everything.

With the tests' fake clock, each chunk "arrives" 0.25 seconds after the previous one and the
final message takes 0.1 seconds more, so two chunks give `ttft_s == 0.25` and `total_s == 0.6`.
If no text arrives at all (a refusal with empty content), the loop body never runs and `ttft`
stays `None`, which is the honest answer: there was no first token.

```python
    return {
        "text": "".join(chunks),
        "usage": _usage_dict(final.usage),
        "stop_reason": final.stop_reason,
        "model": model,
        "ttft_s": ttft,
        "total_s": total,
    }
```

Lines 65 to 72 return a plain dictionary with the same six keys every time. Note what this
function does **not** do: it doesn't check `stop_reason`. Fetching and judging are separate on
purpose, so that `with_retries` can retry a fetch without retrying a judgment (see below).

## `cost_usd` (lines 75 to 83)

```python
def cost_usd(usage: dict[str, int], model: str, prices: dict[str, dict[str, float]] = PRICES) -> float:
    """Price a usage record. Missing fields count as zero; unknown models raise KeyError."""
    p = prices[model]
    return (
        usage.get("input_tokens", 0) * p["input"]
        + usage.get("output_tokens", 0) * p["output"]
        + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]
        + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
    ) / 1_000_000
```

Each of the four token kinds is priced at its own rate, then the sum is divided by a million
because prices are per million tokens. As the README explains, with prompt caching the three
input fields are separate quantities that don't overlap, so they are added, never subtracted.

Two deliberate choices about "missing". `usage.get("input_tokens", 0)` uses **`dict.get` with a
default**, so a usage record without cache fields is priced as zero cache tokens. But
`prices[model]` on line 77 uses square brackets, so an unknown model raises `KeyError`. A
missing usage field genuinely means zero; a missing model means a mistake (a typo, or a new
model nobody priced), and a silent zero or a guessed price would produce a wrong bill that
looks right.

What to check in an AI-written version: that all four fields are priced (forgetting cache
reads makes heavily cached workloads look free), and that the unknown-model case still fails
loudly.

## `require_complete` (lines 86 to 95)

```python
def require_complete(result: dict[str, Any]) -> str:
    reason = result["stop_reason"]
    if reason in ("end_turn", "stop_sequence"):
        return result["text"]
    if reason in ("max_tokens", "model_context_window_exceeded"):
        raise TruncatedError(f"response truncated (stop_reason={reason})")
    if reason == "refusal":
        raise RefusalError("model declined; log it, then consider a fallback model or rephrasing")
    raise ValueError(f"unexpected stop_reason for a text reply: {reason}")
```

This is the gate between "the API returned something" and "we can use it". It returns the text
only for the two finished cases (line 89): the model ended its turn, or one of your stop
sequences fired. The two length limits raise `TruncatedError`, a refusal raises `RefusalError`,
and **anything else** raises `ValueError` (line 95).

That last line is the important design choice. Stop reasons such as `tool_use` or `pause_turn`
are legitimate in other contexts, but they are never a finished text reply, and a stop reason
that doesn't exist yet should not be waved through. Naming the good cases and rejecting the
rest is an **allow-list**, and it fails safe. A version that only checks
`if reason == "max_tokens": raise ...` and otherwise returns the text would hand a refusal's
empty string to your user as if it were an answer.

The messages are **f-strings** (`f"...{reason}"`), which put the actual stop reason into the
error text, so a log line tells you what happened without a debugger.

## `is_retryable` (lines 98 to 107)

```python
def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, anthropic.RateLimitError):
        return exc.response.headers.get("retry-after") is not None
    if isinstance(exc, anthropic.InternalServerError):  # 5xx, including 529 overloaded
        return True
    if isinstance(exc, anthropic.APIConnectionError):  # includes APITimeoutError
        return True
    return False
```

The SDK raises a different exception class for each kind of failure, and this function sorts
them. `isinstance(exc, SomeClass)` is `True` if `exc` is that class **or a subclass of it**,
which is why one check for `APIConnectionError` also covers timeouts (the comment on line 105
notes that `APITimeoutError` is a kind of connection error).

Three groups are retryable: a 429 rate limit that came with a `retry-after` header, any
server-side error (the comment on line 103 notes this includes 529, overloaded), and
connection problems. Everything else, including 400, 401, and 404, and also your own bugs such
as a `ValueError`, returns `False` and is raised immediately.

Line 102 handles the spend-cap case from the lesson: a 429 **without** `retry-after` usually
means the monthly spend cap, and retrying can't help. `exc.response.headers.get(...)` reads the
header from the HTTP response attached to the exception; `is not None` turns "header present"
into `True`.

Why classes and not messages? Matching on error text (`if "overloaded" in str(exc)`) breaks
the day the wording changes. The README says it directly: catch the typed classes, never match
on message strings. This version is narrower than the browser exercise's status-code set: a
408 or a 409 (`ConflictError`) matches none of the three checks here, so it is not retried.
That is a reasonable choice for this lab, and a good example of something to notice and decide
on deliberately when you review someone else's retry policy.

## `backoff_delay` (lines 110 to 122)

```python
def backoff_delay(attempt: int, *, base: float = 0.5, cap: float = 8.0,
                  retry_after: float | None = None, rng: Callable[[], float] = random.random) -> float:
    delay = rng() * min(cap, base * 2**attempt)
    if retry_after is not None:
        delay = max(delay, retry_after)
    return delay
```

This is exponential backoff with full jitter, the same math as the in-browser exercise. The
ceiling `min(cap, base * 2**attempt)` doubles each attempt (0.5, 1, 2, 4, 8 seconds) and stops
at the cap. Multiplying by `rng()`, a random number from 0 up to 1, spreads the actual delay
uniformly below that ceiling, so many clients that failed together don't retry together. If
the server sent `retry-after`, `max` makes sure we never wait less than it asked.

`rng` is injected for the same reason as `clock`: a test passes `rng=lambda: 1.0` (a **lambda**
is a one-line unnamed function) to pin the delay at the ceiling and check the math exactly.

## `_retry_after_seconds` (lines 125 to 133)

```python
def _retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
```

This helper digs the `retry-after` value out of an exception, if there is one. Not every
exception has an HTTP response: a connection error never got one. So line 126 uses
`getattr(exc, "response", None)`, which returns `None` instead of raising `AttributeError`.

Header values are strings, so `float(value)` converts `"5"` to `5.0`. The `try` / `except
ValueError` block catches the case where the header holds something that isn't a plain number:
instead of crashing the retry loop over a header it can't read, the function returns `None`
and the normal backoff applies. `x if condition else y` on line 131 is a **conditional
expression**, a one-line if/else.

This is defensive in the right place. A retry wrapper runs exactly when things are already
going wrong, so it must not add a new failure of its own.

## `with_retries` (lines 136 to 153)

```python
def with_retries(fn, *, max_attempts=4, base=0.5, cap=8.0, sleep=time.sleep, rng=random.random):
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 (we re-raise anything not retryable)
            if not is_retryable(exc) or attempt + 1 >= max_attempts:
                raise
            sleep(backoff_delay(attempt, base=base, cap=cap, retry_after=_retry_after_seconds(exc), rng=rng))
    raise AssertionError("unreachable")
```

(The excerpt drops the type hints to fit; see lines 136 to 144 for the full signature.)

`fn` is a function with no arguments that makes one attempt. The caller wraps its real call in
a lambda: `with_retries(lambda: stream_reply(client, "..."))`. Passing a function rather than a
result is what lets the wrapper call it again.

The loop runs at most `max_attempts` times (`range(4)` gives 0, 1, 2, 3). Inside, `try` /
`except Exception as exc` catches any error from the attempt. Line 150 then decides: if the
error isn't retryable, or this was the last attempt, a bare `raise` (line 151) **re-raises the
same exception** with its original traceback, so the caller sees the real error, not a
wrapper's. Otherwise, line 152 sleeps for the backoff delay and the loop tries again. On
success, `return fn()` (line 148) leaves the function immediately.

`except Exception` is broad, which linters flag (the `noqa: BLE001` comment silences that
warning and says why). It's safe here only because every non-retryable error is re-raised
unchanged on the next line. An AI-written version that catches broadly and then returns `None`
or logs and continues would swallow your bugs.

`sleep` is injected too: the tests pass `sleeps.append`, so instead of actually waiting, each
delay is recorded in a list and checked. A two-failure run with `rng=lambda: 1.0` records
`[0.5, 1.0]`.

Two details worth noticing as a reviewer:

- **What gets retried.** In the `__main__` block, `with_retries` wraps `stream_reply` only, and
  `require_complete` runs afterwards. So a truncated reply is never retried, which is right:
  the identical request would usually truncate again. If you wrapped both inside the lambda,
  `TruncatedError` would still not be retried (it isn't an SDK error), but the boundary would be
  less obvious.
- **Line 153.** `raise AssertionError("unreachable")` is there because every path through the
  loop either returns or raises, so execution should never fall out of it. That is true for
  any `max_attempts` of 1 or more. With `max_attempts=0`, though, the loop body never runs and
  you get this `AssertionError` without a single call being made. Nothing validates the
  argument, so "unreachable" is slightly overstated.

## The `__main__` block (lines 156 to 162)

```python
if __name__ == "__main__":
    client = anthropic.Anthropic(max_retries=0)
    result = with_retries(lambda: stream_reply(client, "In two sentences: what is a token, for an LLM?"))
    print(require_complete(result))
```

`if __name__ == "__main__":` runs only when you execute the file directly
(`python work.py`), not when the tests import it. That's how one file can be both a library
and a script.

`anthropic.Anthropic()` reads `ANTHROPIC_API_KEY` from the environment, so the key never
appears in code. `max_retries=0` turns off the SDK's own retries, which (per the README) would
otherwise retry connection errors, 408, 409, 429, and 5xx responses twice by default. Turning
them off lets you watch your wrapper work. In production, pick one retry layer: two stacked
layers multiply the worst-case wait.

## What the tests check

**`stream_reply` (3 tests).** With a fake client and a fake clock: the text is joined from
chunks, usage is converted with `None` becoming 0, TTFT is measured at the first chunk (0.25 s)
and total includes the final message (0.6 s). The request is well formed: one user message,
`system` present only when given and as a top-level field, and no `temperature`. A reply with
no text has `ttft_s` of `None`.

**`cost_usd` (3 tests).** Basic input and output pricing, all four fields priced at their own
rates on Opus, custom price tables, and `KeyError` for an unknown model.

**`require_complete` (3 tests, 5 cases).** `end_turn` and `stop_sequence` return text; both
truncation reasons raise `TruncatedError`; `refusal` raises `RefusalError`; and `tool_use`
raises `ValueError`, which is how the tests confirm the allow-list.

**Retries (5 tests).** `is_retryable` on real SDK exception classes built with fake HTTP
responses: 429 with and without `retry-after`, 500, 529, a connection error, 400, 401, 404, and
a plain `ValueError`. `backoff_delay` math at fixed `rng` values. `with_retries` recovers from
two transient errors with delays of 0.5 and 1.0, honors a `retry-after` of 5, fails fast on a
400 after exactly one call, and gives up after exactly `max_attempts` calls.

**Safety (1 test).** Neither `starter.py` nor `solution.py` contains anything that looks like an
API key.

**Live (2 tests, need a key).** A real short reply on Haiku that finishes and costs under a
cent, and a real `max_tokens=20` call that is detected as truncated.

**What they don't check.** That `with_retries` actually waits (sleep is faked), the
distribution of jittered delays inside `with_retries`, a non-numeric `retry-after` header,
`max_attempts=0`, a 408 or 409, or a `stop_reason` of `pause_turn`. The live tests check that
the real SDK matches the fakes' shape, but only on one model.

## Review questions

1. `stream_reply` returns the stop reason but doesn't check it. Why is it better to check it in
   a separate `require_complete` function?

   <details><summary>Answer</summary>

   Fetching and judging are different jobs with different failure handling. `with_retries`
   wraps the fetch, so transient network errors get retried. A truncated or refused answer is
   not a network error, and retrying the identical request would usually give the same result
   at double the cost. Keeping the judgment outside the retried function makes that boundary
   explicit, and it also lets you test each one on its own.

   </details>

2. An AI rewrites line 102 as `return True`, saying "429 always means slow down". What breaks?

   <details><summary>Answer</summary>

   A 429 with no `retry-after` header (usually the monthly spend cap) would now be retried. Each
   retry fails the same way, so the caller waits through the whole backoff schedule for nothing,
   and a batch job retries every request. The test
   `test_is_retryable_classification` catches it with its "spend cap" assertion.

   </details>

3. Why does `_usage_dict` use `getattr(usage, f, 0) or 0` rather than just `usage.f` or
   `getattr(usage, f)`?

   <details><summary>Answer</summary>

   Two different kinds of missing. `getattr(usage, f, 0)` handles an attribute that doesn't
   exist, and `or 0` handles one that exists but is `None` (the fake usage has
   `cache_creation_input_tokens=None`). `usage.f` would look for an attribute literally named
   `f`; the name has to come from the string, which is what `getattr` does. Without the
   fallbacks, `int(None)` raises `TypeError` on responses without caching.

   </details>

4. Line 149 catches every `Exception`. A linter flags it. Is it a bug here?

   <details><summary>Answer</summary>

   No, because line 151 re-raises every error that isn't retryable, unchanged, with a bare
   `raise`. Your own bugs (a `ValueError`, a `KeyError`) still surface immediately. It would be a
   bug if the `except` block returned `None`, logged and continued, or wrapped the error in a
   new generic exception, because callers would lose the real error type.

   </details>

5. What happens if you call `with_retries(fn, max_attempts=0)`?

   <details><summary>Answer</summary>

   `range(0)` is empty, so `fn` is never called and the function raises
   `AssertionError("unreachable")` from line 153. The comment assumes at least one attempt. A
   stricter version would raise `ValueError("max_attempts must be at least 1")` at the top. No
   test covers this, which is typical: edge cases nobody thought of are also edge cases nobody
   tested.

   </details>
