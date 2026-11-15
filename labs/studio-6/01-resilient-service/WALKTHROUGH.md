# Walkthrough: a resilient LLM service

## What this code does

`solution.py` is a small web service around a Claude call that keeps behaving sensibly when the
model provider doesn't. When a request fails, it decides what kind of failure it was, retries
only the kinds worth retrying (with randomized, growing waits), stops calling a model that keeps
failing (a circuit breaker), falls back from Opus to Sonnet, and, if both are down, returns a
polite static message instead of an error page. It does the same for streamed replies, with one
extra rule: once any text has reached the user, it never switches models mid-answer.

The file is organized in layers, top to bottom: error types and how SDK errors map onto them;
time (a clock you can fake); retries; the circuit breaker; the service core (`ResilientLLM`);
the adapter that talks to the real Anthropic SDK; and an optional FastAPI web layer.

The design idea worth taking away: **the resilience logic never touches the SDK or the real
clock directly.** It talks to a two-method `ModelClient` interface and a `Clock` interface. In
production those are the real SDK and `time.monotonic`; in the tests they are fakes, so an hour
of retries, timeouts, and breaker resets runs in milliseconds with no API key. When you review
AI-written service code, this is the first thing to look for: can you test the failure paths
without a network?

## How to read this lab

Open `work.py` beside this page. It starts as a copy of `solution.py`, so the line numbers below
match it until you change something. Read a section here, then the code it points to.

Run the tests from VS Code's **Testing** panel (the flask icon): expand
`studio-6/01-resilient-service` and press the run button. Everything except the one `live` test
runs without an API key, and the two HTTP tests are skipped unless FastAPI is installed (see the
README). To see a test fail on purpose, change something small in `work.py` (make
`record_failure` skip the half-open branch, say), rerun, read the message, and undo it.

## Imports and constants (lines 9 to 25)

```python
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator, Optional, Protocol

from pydantic import BaseModel, Field

PRIMARY_MODEL = "claude-opus-5-5"
FALLBACK_MODEL = "claude-sonnet-5-5"
```

- `dataclasses` and `typing` are standard library. `typing` supplies **type hints**: the
  annotations like `Optional[float]` (meaning "a float or `None`") and `Callable[[float], object]`
  ("a function that takes a float"). Hints don't change behavior; they document what each piece
  expects, and editors use them to catch mistakes.
- `pydantic` validates incoming web requests (used at the very bottom).
- The two model ids and `DEGRADED_MESSAGE` are **constants**: one place to change them. Notice
  the degraded message says the request "was not processed", which is honest and tells the user
  what to do.
- `SERVER_FALLBACK_MODELS` (line 25) is the set of models that accept Anthropic's server-side
  refusal fallback, according to the docs on the review date (see the README). It's a **set**, so
  `model in SERVER_FALLBACK_MODELS` is a fast membership test.

Notice that `anthropic` itself is not imported at the top. It is imported inside the functions
that need it (lines 76, 352, 363, 378). That keeps the resilience core importable and testable
even where the SDK isn't installed. Reviewers sometimes "fix" this by moving the import up; it
works, but it ties every test to the SDK.

## The error types (lines 31 to 61)

```python
class ModelError(Exception): ...
class TransientError(ModelError):
    def __init__(self, message: str = "", retry_after: Optional[float] = None, status: Optional[int] = None):
class DeadlineExceeded(TransientError): ...
class PermanentError(ModelError): ...
class Refused(ModelError): ...
```

These are custom **exception classes**. A class written `class TransientError(ModelError)`
**inherits** from `ModelError`: every `TransientError` is also a `ModelError`, so code can catch
the specific kind or the whole family.

The three kinds map to three different reactions:

- **Transient** (lines 35 to 41): rate limits, overload, server errors, timeouts. Worth retrying.
  It carries `retry_after`, the server's hint about how long to wait, and the HTTP `status`.
  `super().__init__(message)` runs the parent class's constructor so the message still prints
  normally.
- **Permanent** (lines 48 to 53): bad request, bad key, spend cap. Retrying sends the same broken
  request and fails the same way, so don't.
- **Refused** (lines 56 to 61): the model declined. The service is healthy; another model might
  answer. It keeps the refusal `category` for logging.

`DeadlineExceeded` (lines 44 to 45) inherits from `TransientError`. That's convenient (any
`except TransientError` also catches it) but it has a consequence in `complete`, covered in the
review questions and in `CHANGE.md`.

## `_retry_after_seconds` (lines 64 to 71)

```python
value = headers.get("retry-after") if headers is not None else None
...
try:
    return max(0.0, float(value))
except ValueError:
    return None
```

Reads the `retry-after` header as a number of seconds. The leading underscore in the name is a
Python convention for "internal helper, not part of the public interface".

- The **conditional expression** on line 65 handles a missing headers object.
- `try` / `except ValueError` (lines 68 to 71) catches the case where the header isn't a number.
  HTTP also allows a date in this header; the comment says this code treats that as absent rather
  than guessing. That's a reasonable, documented simplification.
- `max(0.0, ...)` turns a negative value into zero, so the code can never be told to sleep a
  negative amount (one of the test fakes asserts on exactly that).

## `classify_exception` (lines 74 to 91)

```python
if isinstance(exc, anthropic.APIConnectionError):  # includes APITimeoutError
    return TransientError(f"connection: {exc}")
if isinstance(exc, anthropic.APIStatusError):
    ...
    if details.get("error_code") == "enforced_spend_limit_reached":
        return PermanentError("monthly spend cap reached", status=status)
    if status in (408, 409, 429) or status >= 500:
        return TransientError(..., retry_after=_retry_after_seconds(exc.response.headers), status=status)
    return PermanentError(str(exc), status=status)
```

This is the decision table that turns whatever the SDK raised into one of the three kinds.

- `isinstance(exc, X)` checks whether an object is an instance of a class (or a subclass of it).
  The order of checks matters: our own errors pass straight through (line 78), connection
  problems (including timeouts, which the SDK models as a subclass) are transient, and status
  errors are decided by HTTP status.
- Lines 84 and 85 dig into the error body defensively. `exc.body if isinstance(exc.body, dict)
  else {}` guards against a body that isn't a dict, and `(body.get("error") or {}).get("details")
  or {}` chains `.get` calls with `or {}` so a missing level returns an empty dict instead of
  crashing. This is a common Python idiom for reading nested JSON that may be incomplete.
- The spend-cap check comes **before** the status check, on purpose. The spend cap arrives as a
  429, which looks like a rate limit, but it keeps failing until the month resets. Checked in the
  other order, the service would retry a request that cannot succeed. The README calls this out,
  and a test checks it.
- Anything unexpected (line 91) is treated as permanent. Failing safe here means an unknown
  error is reported, not retried in a loop. `{exc!r}` in the **f-string** uses the `repr` form,
  which includes the exception's class name.

**Reviewing AI-written versions:** check the status list against the docs rather than trusting
it, and check that the special cases come before the general rules. A version that treats every
4xx as permanent misses 408 (request timeout), 409 (conflict), and 429 (rate limit).

## The clock (lines 97 to 107)

```python
class Clock(Protocol):
    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...
```

A `Protocol` describes a shape: "anything with a `now()` and a `sleep()` method". It's Python's
version of an interface. Nothing has to inherit from it; the test's `FakeClock` just has the two
methods. The `...` bodies are literally the Ellipsis object, used as a placeholder.

`SystemClock` is the real implementation. It uses `time.monotonic()`, not `time.time()`. A
monotonic clock never jumps backward (wall-clock time can, when the system adjusts it), so
durations measured with it are always sane. For timeouts and deadlines, always use a monotonic
clock; an AI-written version that uses `time.time()` usually works, until the day it doesn't.

## `RetryPolicy` and `backoff_delay` (lines 113 to 123)

```python
@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    attempt_timeout: float = 30.0

    def backoff_delay(self, retry_number: int, rng: random.Random) -> float:
        ceiling = min(self.max_delay, self.base_delay * (2 ** (retry_number - 1)))
        return rng.uniform(0, ceiling)
```

`@dataclass` is a **decorator** that writes the boring parts of a class for you (the constructor,
a readable printout, equality) from the annotated fields. `frozen=True` makes instances
read-only: a policy can't be changed halfway through a request by accident.

`backoff_delay` is **capped exponential backoff with full jitter**. The ceiling doubles with each
retry (0.5, 1, 2, 4, 8 seconds) and stops at `max_delay`. Then the actual wait is a uniform
random draw between 0 and that ceiling. `2 ** n` is exponentiation.

Why random? If a thousand clients all hit an overload at the same moment and all retry after
exactly 1 second, they all hit it again at the same moment. Spreading the retries across the
whole range breaks up that stampede. The test "full jitter starts at zero" exists because a
common variant waits between half the ceiling and the ceiling, which spreads retries less.

`rng` is passed in (rather than calling `random.uniform` directly) so tests can use a seeded
generator and get repeatable results.

## `call_with_retries` (lines 126 to 154)

```python
def call_with_retries(fn, *, policy, clock, rng, deadline=None):
    attempt = 0
    while True:
        attempt += 1
        timeout = policy.attempt_timeout
        if deadline is not None:
            remaining = deadline - clock.now()
            if remaining <= 0:
                raise DeadlineExceeded("request deadline exceeded")
            timeout = min(timeout, remaining)
        try:
            return fn(timeout)
        except TransientError as err:
            if attempt >= policy.max_attempts:
                raise
            delay = policy.backoff_delay(attempt, rng)
            if err.retry_after is not None:
                delay = max(delay, err.retry_after)
            if deadline is not None and clock.now() + delay >= deadline:
                raise
            clock.sleep(delay)
```

The heart of the lab. It calls `fn(timeout)` and, on a transient failure, waits and tries again.

- The `*` in the parameter list (line 128) means everything after it is **keyword-only**: callers
  must write `policy=...`, `clock=...`. That prevents mixing up arguments of the same type.
- `fn` is a **callable**: a function passed as an argument. The retry loop doesn't know or care
  what it calls, which is why the same function serves both `complete` and `stream_events`.
- `while True:` loops until something returns or raises.
- **Per-attempt timeout that shrinks** (lines 138 to 143): each attempt gets the policy's
  timeout, or whatever is left of the overall deadline if that's less. With a 45 second deadline
  and a 30 second attempt timeout, the first attempt gets 30 and the second gets at most 15.
- **Only transient errors are caught** (line 146). A `PermanentError` or `Refused` passes straight
  through on the first try. This is the classification paying off.
- **A bare `raise`** (lines 148 and 153) re-raises the error currently being handled, with its
  original traceback. That's better than `raise err` or raising a new error, because the caller
  sees exactly what failed.
- **`retry-after` is a minimum** (lines 150 and 151): if the server says wait 5 seconds, wait at
  least 5, even if the jitter drew 0.2.
- **Never sleep past the deadline** (lines 152 and 153): if the wait would end after the deadline,
  give up now instead of sleeping and then failing.
- Attempt counting: `max_attempts` counts the first call, so 3 means one call plus two retries,
  and there's no sleep after the last one.

**Reviewing AI-written versions:** look for retries on every exception (`except Exception`),
sleeping without a deadline check, ignoring `retry-after`, and off-by-one attempt counts. The
tests in section 3 of the test file cover each of these.

## `CircuitBreaker` (lines 160 to 202)

```python
@property
def state(self) -> str:
    if self.opened_at is None:
        return "closed"
    if self.clock.now() - self.opened_at >= self.reset_timeout:
        return "half_open"
    return "open"
```

This is the same breaker as the week 1 in-browser exercise, with type hints and defaults. Closed
lets calls through; after `failure_threshold` consecutive failures it opens and rejects calls
instantly; after `reset_timeout` seconds it goes half-open and lets exactly one trial call
through.

- `state` (lines 171 to 177) is a **property** (the `@property` decorator makes a method readable
  like an attribute, `br.state`). It is computed from `opened_at` and the clock, never stored, so
  nothing has to remember to flip "open" to "half_open" when time passes.
- `allow` (lines 179 to 188) hands out the single half-open trial by setting
  `trial_in_flight = True`. Everyone else is refused until the trial reports back.
- `record_success` (lines 190 to 193) resets everything, which is what makes only *consecutive*
  failures count.
- `record_failure` (lines 195 to 202): a failed trial reopens the breaker and restarts the timer
  from now (line 197) and frees the trial slot (line 198). Otherwise it counts and opens at the
  threshold.
- `self.clock = clock or SystemClock()` (line 166) uses `or` to supply a default: if no clock is
  passed, use the real one. (Don't write `clock=SystemClock()` as the default in the signature;
  defaults are created once and shared, which is harmless here but a classic bug with lists.)

**Reviewing AI-written versions:** check that a failed half-open trial both restarts the timer
and clears the trial flag. Dropping either produces a breaker that hammers a sick service or
never recovers.

## The interface, `Reply`, and `format_sse` (lines 208 to 226)

```python
class ModelClient(Protocol):
    def complete(self, *, model: str, messages: list, max_tokens: int, timeout: float) -> str: ...
    def stream(self, *, model: str, messages: list, max_tokens: int, timeout: float) -> Iterable[str]: ...

@dataclass
class Reply:
    text: str
    model: Optional[str]  # None when the service degraded to the static message
    notes: list = field(default_factory=list)
```

`ModelClient` is the two-method seam between the resilience logic and the SDK. `complete`
returns text; `stream` returns something you can loop over that yields text chunks.

`Reply` is a **dataclass** holding the result. `field(default_factory=list)` gives each `Reply`
its own new empty list. Writing `notes: list = []` instead is an error in a dataclass, precisely
because a shared mutable default would leak notes between replies. `degraded` (lines 219 to 221)
is a property derived from `model`, so it can never disagree with it.

`format_sse` (lines 224 to 226) turns one `(event, data)` pair into the text/event-stream wire
format: an `event:` line, a `data:` line with JSON, and a blank line. `json.dumps` produces the
JSON. This is the format the week 1 `parse_sse` exercise reads.

## `ResilientLLM.__init__` (lines 229 to 249)

```python
self.models = list(models or [PRIMARY_MODEL, FALLBACK_MODEL])
self.breakers = breakers or {m: CircuitBreaker(clock=self.clock) for m in self.models}
```

The constructor takes the client plus optional overrides for everything else (all keyword-only,
after the `*` on line 234), and fills in defaults with the `x or default` pattern.

- `list(models or [...])` copies the list, so a caller mutating their own list later can't change
  the service's model chain.
- The **dict comprehension** on line 247 builds one breaker per model. One breaker per model,
  not one for the whole service, is the point: Opus being down shouldn't stop calls to Sonnet.
- Every breaker shares the service's clock, so tests that move the fake clock move everything.

## `complete` (lines 251 to 282)

```python
deadline = self.clock.now() + self.request_deadline
for model in self.models:
    breaker = self.breakers[model]
    if not breaker.allow():
        notes.append(f"{model}: circuit open, skipped")
        continue
    try:
        text = call_with_retries(lambda timeout, m=model: self.client.complete(...), ...)
    except Refused as err:
        breaker.record_success()
        ...
        continue
    except PermanentError:
        breaker.record_success()
        raise
    except TransientError as err:
        breaker.record_failure()
        ...
        continue
    breaker.record_success()
    return Reply(text=text, model=model, notes=notes)
return Reply(text=DEGRADED_MESSAGE, model=None, notes=notes)
```

The model chain for a normal (non-streaming) request.

- **One deadline for the whole chain** (line 252). It is computed once, before the loop, so the
  fallback gets whatever time the primary left, not a fresh 60 seconds. A test checks that the
  whole chain stays inside the budget.
- **An open breaker skips the model without calling it** (lines 256 to 258): fail fast.
- **The lambda** on line 261 adapts `client.complete` (which needs model, messages, and so on) to
  the one-argument `fn(timeout)` shape that `call_with_retries` expects. `m=model` is a
  **default-argument capture**: it freezes the current value of `model` into the lambda. Without
  it, a lambda that ran later would see whatever `model` was at that time. Here the lambda runs
  immediately, so it would work either way, but the habit prevents a real bug in loops.
- **Each kind of failure gets its own reaction** (lines 269 to 279):
  - A refusal counts as a *success* for the breaker (the service answered), and the chain moves to
    the next model. Counting refusals as failures would let a few refused prompts take Opus
    offline for everyone.
  - A permanent error also counts as a success (the service is reachable; the request is the
    problem) and is re-raised: a malformed request fails on every model, so there's no point
    falling back.
  - A transient failure (after retries) counts against the breaker and moves on.
- The `except` clauses are checked top to bottom, and the first match wins. Order matters
  because `DeadlineExceeded` is a `TransientError` and would be caught by that last clause.
- After the loop, if no model answered, the degraded `Reply` with `model=None`. `notes` explains
  what happened to each model, which is what your logs and traces will want in week 3.

**Something to notice:** if the primary uses up the whole deadline, the loop still reaches the
fallback, whose `call_with_retries` immediately raises `DeadlineExceeded` without calling it.
That lands in `except TransientError` and calls `breaker.record_failure()` on a model that was
never called. During a slow primary outage, that can trip a perfectly healthy fallback's
breaker. `CHANGE.md` asks you to fix this.

## `stream_events` (lines 284 to 342)

```python
def open_stream(timeout, m=model):
    iterator = iter(self.client.stream(model=m, ...))
    return next(iterator, None), iterator
...
first, iterator = call_with_retries(open_stream, ...)
...
# From here on the client has seen output, so we never switch models.
yield ("meta", {"model": model, "notes": notes})
```

The streaming version of the chain. It is a **generator**: a function containing `yield`, which
produces a sequence of values one at a time, pausing between them. The web layer sends each
`(event, data)` pair to the browser as it's produced.

- **Getting the first chunk inside the retry** (lines 294 to 303). `open_stream` starts the
  stream and pulls the first chunk with `next(iterator, None)` (the `None` is a default returned
  if the stream is empty, instead of raising `StopIteration`). Because this happens inside
  `call_with_retries`, a failure *before any text* is retried and can fall back, exactly like
  `complete`. It returns a **tuple** of the first chunk and the rest of the iterator.
- **The point of no return** (line 317). After the `meta` event, text is flowing to the user.
  Switching models now would splice two different answers together, so from here a failure
  becomes an `error` event, not a fallback.
- **The total deadline is checked between chunks** (lines 323 to 328). The README explains why:
  the SDK's timeout bounds each read (the gap between chunks), not the whole stream. If the
  deadline passes, the code closes the stream (`getattr(iterator, "close", None)` fetches the
  `close` method only if the object has one) and reports a `deadline` error.
- **Mid-stream refusal** (lines 330 to 333) tells the client `discard_partial: True`: the text so
  far belongs to an answer the model then declined, so the UI should remove it.
- **Other mid-stream errors** (lines 334 to 338): `except ModelError` catches the whole family.
  Only transient ones count against the breaker. The partial text is kept
  (`discard_partial: False`), since it isn't harmful, just incomplete.
- A permanent error before any text (lines 308 to 311) yields an `error` event and `return`s (in a
  generator, `return` simply ends the sequence).

**Reviewing AI-written versions:** the most common mistake is to wrap the whole stream in the
retry loop, so a failure after the first token silently restarts on another model and the user
sees the answer start over (or two answers mashed together). Check where the "no switching"
line is.

## `AnthropicModelClient` (lines 348 to 393)

```python
self._client = client or anthropic.Anthropic(max_retries=0)
...
client = self._client.with_options(timeout=timeout, max_retries=0)
...
except anthropic.APIError as exc:
    raise classify_exception(exc) from exc
if response.stop_reason == "refusal":
    raise Refused(getattr(details, "category", None))
```

The adapter between the real SDK and the `ModelClient` interface. It is the only part of the
service that knows about the SDK.

- **SDK retries are off** (lines 354, 365, 381). The SDK retries on its own by default; this
  service retries in `call_with_retries`, so leaving both on would multiply attempts (the README
  works the numbers). `with_options` makes a copy of the client with a per-call timeout.
- **Server-side refusal fallback** (lines 357 to 360): for supported models, it opts into the beta
  the README describes, by adding extra keyword arguments. `**self._extra(model)` **unpacks** a
  dict into keyword arguments; an empty dict adds nothing.
- **`raise ... from exc`** (lines 371 and 390) raises our classified error while keeping the
  original SDK exception attached as its cause, so a traceback shows both.
- A refusal is a normal response with `stop_reason == "refusal"`, so it is turned into the
  `Refused` exception here (lines 372 to 374 and 391 to 393). `getattr(obj, name, None)` reads an
  attribute that might not exist without crashing.
- `"".join(block.text for block in response.content if block.type == "text")` (line 375) keeps
  only text blocks and glues them together.
- `stream` (lines 377 to 393) is a generator that uses `with ... as stream:`, a **context
  manager**: the `with` block guarantees the stream's connection is closed when the block ends,
  even on an error. It yields each text chunk, then checks the final message for a refusal.

## The HTTP layer (lines 399 to 432)

```python
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
```

- `ChatRequest` is a **pydantic model**: FastAPI uses it to validate the request body, so an empty
  or huge message is rejected with a 422 before any model is called. Validating at the edge is
  cheaper than letting a bad request reach the model.
- `create_app` (lines 403 to 427) imports FastAPI inside the function (so FastAPI stays optional)
  and defines three endpoints with **decorators** like `@app.post("/chat")`, which register the
  function below as the handler for that path.
- `/healthz` reports each breaker's state, which is what a load balancer or a dashboard would
  poll.
- `/chat/stream` wraps the event generator in a `StreamingResponse` with the
  `text/event-stream` media type. The **generator expression** `(format_sse(event, data) for
  event, data in events)` formats each event lazily, as it arrives. The `X-Accel-Buffering: no`
  header asks proxies like nginx not to buffer the stream.
- `build_default_app` (lines 430 to 432) is the production wiring: real SDK, real clock, Opus then
  Sonnet. `serve.py` calls it.

## What the tests check

All offline tests use a `FakeModelClient` that follows a script per model (a string means
success, an exception is raised) and a `FakeClock` that only moves when someone sleeps or the
test advances it.

- **Backoff (section 1):** delays stay inside the capped ceiling, use the whole range from zero,
  and differ between clients with different random generators.
- **Classifying SDK errors (section 2):** real SDK exception objects are built and classified: 429
  with `retry-after`, 500 and 529, timeouts and dropped connections, 400 and 401, and the
  spend-cap 429 that must be permanent.
- **Retries (section 3):** success after two failures with exactly two sleeps; giving up after
  `max_attempts`; no retries for permanent errors or refusals; `retry-after` as a minimum; and
  per-attempt timeouts that shrink to fit the deadline without ever running past it.
- **Circuit breaker (section 4):** opens after consecutive failures, resets on success, allows one
  half-open trial, and a failed trial reopens with a fresh timer.
- **`complete` (section 5):** primary success; fallback after retries with a note; refusal falls
  back without counting as a failure; bad requests don't fall back; everything down degrades; an
  open breaker skips the primary without calling it; and one deadline covers the whole chain.
- **Streaming (section 6):** the happy path event sequence, fallback before the first token, no
  model switch after it, `discard_partial` on a mid-stream refusal, the total deadline, and
  degradation.
- **HTTP (section 7, needs FastAPI):** `/chat`, `/healthz`, input validation, and the SSE format.
- **Live (section 8):** one short real call and one short real stream to Haiku.

What they don't cover: concurrency (two requests racing for the same half-open trial in
different threads), the HTTP-date form of `retry-after`, the real server-side fallback behavior,
and, as noted under `complete`, what a deadline-exhausted fallback does to its breaker. Those are
the places to think hardest when reviewing changes.

## Review questions

1. Why does `classify_exception` check for the spend-cap error before checking the status code?

<details>
<summary>Answer</summary>

The spend cap arrives as a 429, the same status as a rate limit, and `status in (408, 409, 429)`
would classify it as transient. But it keeps failing until the month resets, so retrying it only
wastes time and delays the user's error. Special cases have to come before the general rule
that would otherwise swallow them.

</details>

2. An AI assistant changes the `except Refused` branch in `complete` to call
   `breaker.record_failure()` instead of `record_success()`, saying "a refusal is a failed call".
   What goes wrong in production?

<details>
<summary>Answer</summary>

A handful of users sending prompts that Opus refuses would open Opus's breaker (five
consecutive refusals with the default threshold), and then *every* user would be routed to
Sonnet or get the degraded message for the next 30 seconds, even though Opus is perfectly
healthy. The breaker measures whether the service is up; refusals are about the request, not the
service. The test `test_refusal_falls_back_without_counting_as_an_outage` catches it.

</details>

3. In `stream_events`, why is the first chunk fetched inside `call_with_retries` (in
   `open_stream`) rather than after it?

<details>
<summary>Answer</summary>

Many failures (overload, a dropped connection) happen when the stream starts, before any text
arrives. Fetching the first chunk inside the retry means those failures are retried and can fall
back to Sonnet, and the user never knows. If the first chunk were fetched after the retry
returned, a failure at that point would already be past the point of no return and would surface
as an `error` event, even though no text had reached the user yet.

</details>

4. The primary hangs until its timeouts fire and uses up the entire 60 second deadline. What
   happens to the fallback model's circuit breaker, and why does it matter?

<details>
<summary>Answer</summary>

The loop moves on to the fallback, and `call_with_retries` raises `DeadlineExceeded` before
calling it (line 142). Because `DeadlineExceeded` is a subclass of `TransientError`, it lands in
`except TransientError` (line 276), which calls `breaker.record_failure()` on the fallback. After
a few such requests, the healthy fallback's breaker opens, so when the primary is slow the
fallback gets taken offline too, which is exactly when you need it. `CHANGE.md` fixes this.

</details>

5. Why does `RetryPolicy.backoff_delay` take an `rng` argument instead of calling `random.uniform`
   directly?

<details>
<summary>Answer</summary>

So tests can pass a seeded `random.Random` and get the same "random" delays every run, which
makes assertions about timing repeatable. It also lets the test confirm that two clients with
different generators don't retry at the same instant. Passing dependencies in (the clock, the
random generator, the model client) is what makes the whole service testable offline.

</details>
