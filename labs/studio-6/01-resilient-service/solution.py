"""Lab 01 (Studio 6): a resilient LLM service. Reference solution.

The resilience logic (retries, backoff, circuit breakers, fallbacks, deadlines,
streaming) does not depend on any SDK. It talks to a small `ModelClient`
interface, so the tests drive it with a fake client and a fake clock.
`AnthropicModelClient` adapts the official SDK to that interface, and
`create_app` wraps everything in a FastAPI service (FastAPI is optional).
"""
import json
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator, Optional, Protocol

from pydantic import BaseModel, Field

PRIMARY_MODEL = "claude-opus-5-5"
FALLBACK_MODEL = "claude-sonnet-5-5"
DEGRADED_MESSAGE = (
    "The assistant is temporarily unavailable. Your request was not processed; please try again in a minute."
)

# Models that accept the server-side refusal fallback (`fallbacks: "default"`), per the
# refusals-and-fallback docs on the review date. Haiku 5.5 has no server-side fallback.
SERVER_FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-fable-5-2", "claude-fable-5-1"}


# ----------------------------------------------------------------------------- errors


class ModelError(Exception):
    """Base class for the three kinds of failure the service distinguishes."""


class TransientError(ModelError):
    """Worth retrying: rate limits, overload, 5xx, timeouts, dropped connections."""

    def __init__(self, message: str = "", retry_after: Optional[float] = None, status: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after
        self.status = status


class DeadlineExceeded(TransientError):
    """The request's overall time budget ran out."""


class PermanentError(ModelError):
    """Retrying the same request will fail the same way: bad request, bad key, spend cap."""

    def __init__(self, message: str = "", status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class Refused(ModelError):
    """The model declined (stop_reason == "refusal"). The service is healthy; try another model."""

    def __init__(self, category: Optional[str] = None):
        super().__init__(f"refused ({category})")
        self.category = category


def _retry_after_seconds(headers) -> Optional[float]:
    value = headers.get("retry-after") if headers is not None else None
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # HTTP also allows a date here; treat an unparseable value as absent


def classify_exception(exc: Exception) -> ModelError:
    """Map an exception from the anthropic SDK to TransientError, PermanentError, or Refused."""
    import anthropic

    if isinstance(exc, ModelError):
        return exc
    if isinstance(exc, anthropic.APIConnectionError):  # includes APITimeoutError
        return TransientError(f"connection: {exc}")
    if isinstance(exc, anthropic.APIStatusError):
        status = exc.status_code
        body = exc.body if isinstance(exc.body, dict) else {}
        details = (body.get("error") or {}).get("details") or {}
        if details.get("error_code") == "enforced_spend_limit_reached":
            return PermanentError("monthly spend cap reached", status=status)
        if status in (408, 409, 429) or status >= 500:
            return TransientError(str(exc), retry_after=_retry_after_seconds(exc.response.headers), status=status)
        return PermanentError(str(exc), status=status)
    return PermanentError(f"unexpected error: {exc!r}")


# ----------------------------------------------------------------------------- time


class Clock(Protocol):
    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


# ----------------------------------------------------------------------------- retries


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3  # total attempts, including the first
    base_delay: float = 0.5  # seconds
    max_delay: float = 8.0  # cap on any single backoff
    attempt_timeout: float = 30.0  # per-attempt timeout, in seconds

    def backoff_delay(self, retry_number: int, rng: random.Random) -> float:
        """Full jitter: uniform between 0 and min(max_delay, base_delay * 2 ** (retry_number - 1))."""
        ceiling = min(self.max_delay, self.base_delay * (2 ** (retry_number - 1)))
        return rng.uniform(0, ceiling)


def call_with_retries(
    fn: Callable[[float], object],
    *,
    policy: RetryPolicy,
    clock: Clock,
    rng: random.Random,
    deadline: Optional[float] = None,
):
    """Call fn(timeout) until it succeeds, retrying only TransientError."""
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


# ----------------------------------------------------------------------------- circuit breaker


class CircuitBreaker:
    """Closed -> open after `failure_threshold` consecutive failures; half-open after `reset_timeout`."""

    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 30.0, clock: Optional[Clock] = None):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.clock = clock or SystemClock()
        self.failures = 0
        self.opened_at: Optional[float] = None
        self.trial_in_flight = False

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if self.clock.now() - self.opened_at >= self.reset_timeout:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        state = self.state
        if state == "closed":
            return True
        if state == "open":
            return False
        if self.trial_in_flight:
            return False
        self.trial_in_flight = True
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None
        self.trial_in_flight = False

    def record_failure(self) -> None:
        if self.state == "half_open":
            self.opened_at = self.clock.now()
            self.trial_in_flight = False
            return
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = self.clock.now()


# ----------------------------------------------------------------------------- the service core


class ModelClient(Protocol):
    def complete(self, *, model: str, messages: list, max_tokens: int, timeout: float) -> str: ...
    def stream(self, *, model: str, messages: list, max_tokens: int, timeout: float) -> Iterable[str]: ...


@dataclass
class Reply:
    text: str
    model: Optional[str]  # None when the service degraded to the static message
    notes: list = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        return self.model is None


def format_sse(event: str, data: dict) -> str:
    """One server-sent event: named event, JSON data, blank line terminator."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class ResilientLLM:
    def __init__(
        self,
        client: ModelClient,
        models: Optional[list] = None,
        *,
        policy: Optional[RetryPolicy] = None,
        clock: Optional[Clock] = None,
        rng: Optional[random.Random] = None,
        breakers: Optional[dict] = None,
        request_deadline: float = 60.0,
        max_tokens: int = 1024,
    ):
        self.client = client
        self.models = list(models or [PRIMARY_MODEL, FALLBACK_MODEL])
        self.policy = policy or RetryPolicy()
        self.clock = clock or SystemClock()
        self.rng = rng or random.Random()
        self.breakers = breakers or {m: CircuitBreaker(clock=self.clock) for m in self.models}
        self.request_deadline = request_deadline
        self.max_tokens = max_tokens

    def complete(self, messages: list) -> Reply:
        deadline = self.clock.now() + self.request_deadline
        notes = []
        for model in self.models:
            breaker = self.breakers[model]
            if not breaker.allow():
                notes.append(f"{model}: circuit open, skipped")
                continue
            try:
                text = call_with_retries(
                    lambda timeout, m=model: self.client.complete(
                        model=m, messages=messages, max_tokens=self.max_tokens, timeout=timeout
                    ),
                    policy=self.policy,
                    clock=self.clock,
                    rng=self.rng,
                    deadline=deadline,
                )
            except Refused as err:
                breaker.record_success()  # the service answered; it just declined
                notes.append(f"{model}: refused ({err.category})")
                continue
            except PermanentError:
                breaker.record_success()  # reachable; the request itself is the problem
                raise
            except TransientError as err:
                breaker.record_failure()
                notes.append(f"{model}: failed ({err})")
                continue
            breaker.record_success()
            return Reply(text=text, model=model, notes=notes)
        return Reply(text=DEGRADED_MESSAGE, model=None, notes=notes)

    def stream_events(self, messages: list) -> Iterator[tuple]:
        """Yield (event, data) pairs: meta, delta..., then done | error | degraded."""
        deadline = self.clock.now() + self.request_deadline
        notes = []
        for model in self.models:
            breaker = self.breakers[model]
            if not breaker.allow():
                notes.append(f"{model}: circuit open, skipped")
                continue

            def open_stream(timeout, m=model):
                iterator = iter(
                    self.client.stream(model=m, messages=messages, max_tokens=self.max_tokens, timeout=timeout)
                )
                return next(iterator, None), iterator

            try:
                first, iterator = call_with_retries(
                    open_stream, policy=self.policy, clock=self.clock, rng=self.rng, deadline=deadline
                )
            except Refused as err:
                breaker.record_success()
                notes.append(f"{model}: refused ({err.category})")
                continue
            except PermanentError as err:
                breaker.record_success()
                yield ("error", {"type": "bad_request", "message": str(err), "discard_partial": False})
                return
            except TransientError as err:
                breaker.record_failure()
                notes.append(f"{model}: failed ({err})")
                continue

            # From here on the client has seen output, so we never switch models.
            yield ("meta", {"model": model, "notes": notes})
            try:
                if first is not None:
                    yield ("delta", {"text": first})
                for chunk in iterator:
                    if self.clock.now() > deadline:
                        close = getattr(iterator, "close", None)
                        if close:
                            close()
                        yield ("error", {"type": "deadline", "discard_partial": False})
                        return
                    yield ("delta", {"text": chunk})
            except Refused as err:
                breaker.record_success()
                yield ("error", {"type": "refusal", "category": err.category, "discard_partial": True})
                return
            except ModelError as err:
                if isinstance(err, TransientError):
                    breaker.record_failure()
                yield ("error", {"type": "interrupted", "message": str(err), "discard_partial": False})
                return
            breaker.record_success()
            yield ("done", {"model": model})
            return
        yield ("degraded", {"text": DEGRADED_MESSAGE, "notes": notes})


# ----------------------------------------------------------------------------- Anthropic adapter


class AnthropicModelClient:
    """Adapts the anthropic SDK to ModelClient. SDK retries are off: this service retries at one layer."""

    def __init__(self, client=None, server_side_fallbacks: bool = True):
        import anthropic

        self._client = client or anthropic.Anthropic(max_retries=0)
        self._server_side_fallbacks = server_side_fallbacks

    def _extra(self, model: str) -> dict:
        if self._server_side_fallbacks and model in SERVER_FALLBACK_MODELS:
            return {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        return {}

    def complete(self, *, model, messages, max_tokens, timeout) -> str:
        import anthropic

        client = self._client.with_options(timeout=timeout, max_retries=0)
        try:
            response = client.beta.messages.create(
                model=model, max_tokens=max_tokens, messages=messages, **self._extra(model)
            )
        except anthropic.APIError as exc:
            raise classify_exception(exc) from exc
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise Refused(getattr(details, "category", None))
        return "".join(block.text for block in response.content if block.type == "text")

    def stream(self, *, model, messages, max_tokens, timeout):
        import anthropic

        # A float timeout bounds each read (the gap between chunks), not the whole stream.
        client = self._client.with_options(timeout=timeout, max_retries=0)
        try:
            with client.beta.messages.stream(
                model=model, max_tokens=max_tokens, messages=messages, **self._extra(model)
            ) as stream:
                for text in stream.text_stream:
                    yield text
                final = stream.get_final_message()
        except anthropic.APIError as exc:
            raise classify_exception(exc) from exc
        if final.stop_reason == "refusal":
            details = getattr(final, "stop_details", None)
            raise Refused(getattr(details, "category", None))


# ----------------------------------------------------------------------------- HTTP layer (optional FastAPI)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


def create_app(llm: ResilientLLM):
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse

    app = FastAPI(title="Resilient LLM service")

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "breakers": {m: b.state for m, b in llm.breakers.items()}}

    @app.post("/chat")
    def chat(req: ChatRequest):
        reply = llm.complete([{"role": "user", "content": req.message}])
        return {"text": reply.text, "model": reply.model, "degraded": reply.degraded, "notes": reply.notes}

    @app.post("/chat/stream")
    def chat_stream(req: ChatRequest):
        events = llm.stream_events([{"role": "user", "content": req.message}])
        return StreamingResponse(
            (format_sse(event, data) for event, data in events),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def build_default_app():
    """The production wiring: real SDK, real clock, Opus with a Sonnet fallback."""
    return create_app(ResilientLLM(AnthropicModelClient(), [PRIMARY_MODEL, FALLBACK_MODEL]))
