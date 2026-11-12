"""Lab 01 (Studio 6): a resilient LLM service. Your file: fill in the TODOs.

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
    """Map an exception from the anthropic SDK to TransientError, PermanentError, or Refused.

    Rules (from the Claude API errors and rate-limits docs):
    - Lab errors (already a ModelError) pass through unchanged.
    - anthropic.APIConnectionError (this includes APITimeoutError) -> TransientError.
    - anthropic.APIStatusError:
        * a 429 whose body has error.details.error_code == "enforced_spend_limit_reached" -> PermanentError
          (the monthly spend cap: it has no retry-after and keeps failing until access resumes)
        * 408, 409, 429, or any status >= 500 -> TransientError, with retry_after parsed from the
          `retry-after` response header (use _retry_after_seconds(exc.response.headers)) and status set
        * any other status -> PermanentError(status=...)
    - anything else -> PermanentError.
    Hint: exc.status_code, exc.body (may be a dict or None), exc.response.headers.
    """
    import anthropic  # noqa: F401

    # TODO
    raise NotImplementedError


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
        """Full jitter: uniform between 0 and min(max_delay, base_delay * 2 ** (retry_number - 1)).

        retry_number is 1 for the first retry. Use rng.uniform so tests can seed it."""
        # TODO
        raise NotImplementedError


def call_with_retries(
    fn: Callable[[float], object],
    *,
    policy: RetryPolicy,
    clock: Clock,
    rng: random.Random,
    deadline: Optional[float] = None,
):
    """Call fn(timeout) until it succeeds, retrying only TransientError.

    - Attempt at most policy.max_attempts times in total; re-raise the last TransientError.
    - PermanentError and Refused propagate immediately (no retry).
    - Each attempt gets timeout = policy.attempt_timeout, or what is left before `deadline` if that is
      smaller. If nothing is left, raise DeadlineExceeded.
    - Between attempts, sleep policy.backoff_delay(attempt_number, rng) seconds, but at least
      err.retry_after when the error carries one. Use clock.sleep, never time.sleep.
    - If that sleep would reach or pass the deadline, re-raise instead of sleeping.
    """
    # TODO
    raise NotImplementedError


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
        """"closed" if never opened (opened_at is None); "half_open" once reset_timeout has passed
        since opened_at; otherwise "open"."""
        # TODO
        raise NotImplementedError

    def allow(self) -> bool:
        """closed: True. open: False. half_open: True for exactly one trial call (set trial_in_flight),
        then False until that trial is recorded."""
        # TODO
        raise NotImplementedError

    def record_success(self) -> None:
        """Back to closed: reset failures, opened_at, and trial_in_flight."""
        # TODO
        raise NotImplementedError

    def record_failure(self) -> None:
        """half_open: the trial failed, so reopen now (opened_at = now) and clear trial_in_flight.
        Otherwise count a consecutive failure and open when failures reaches failure_threshold."""
        # TODO
        raise NotImplementedError


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
        """Try each model in order under ONE deadline (now + request_deadline) shared by the whole chain.

        For each model:
        - If its breaker does not allow() the call, note it ("<model>: circuit open, skipped") and move on.
        - Call self.client.complete(model=..., messages=..., max_tokens=self.max_tokens, timeout=...)
          through call_with_retries (fn receives the per-attempt timeout).
        - Refused: the service is healthy, so record_success(), add a note, and try the next model.
        - PermanentError: record_success() (the service answered) and re-raise. Do not fall back.
        - TransientError (retries exhausted): record_failure(), add a note, try the next model.
        - Success: record_success() and return Reply(text, model, notes).
        If no model answered, return Reply(DEGRADED_MESSAGE, None, notes).
        """
        # TODO
        raise NotImplementedError

    def stream_events(self, messages: list) -> Iterator[tuple]:
        """Yield (event, data) pairs for a streamed reply. Same deadline and breaker rules as complete().

        Before any text has been sent you may still retry and fall back. To get there, open the stream
        and pull its first chunk inside call_with_retries:

            def open_stream(timeout, m=model):
                iterator = iter(self.client.stream(model=m, messages=messages,
                                                   max_tokens=self.max_tokens, timeout=timeout))
                return next(iterator, None), iterator

        Failures while opening are handled exactly as in complete(), except a PermanentError yields
        ("error", {"type": "bad_request", "message": ..., "discard_partial": False}) and stops.

        Once the stream is open, the model is fixed:
        - yield ("meta", {"model": model, "notes": notes}), then ("delta", {"text": first}) if first is
          not None, then one ("delta", {"text": chunk}) per remaining chunk;
        - before yielding each later chunk, if clock.now() > deadline, close the iterator if it has a
          close() method, yield ("error", {"type": "deadline", "discard_partial": False}) and stop;
        - Refused mid-stream: record_success(), yield ("error", {"type": "refusal", "category": ...,
          "discard_partial": True}) and stop (the partial text must not be shown as an answer);
        - any other ModelError mid-stream: record_failure() if it is transient, yield ("error",
          {"type": "interrupted", "message": ..., "discard_partial": False}) and stop;
        - on normal completion: record_success() and yield ("done", {"model": model}).
        If no model could be opened, yield ("degraded", {"text": DEGRADED_MESSAGE, "notes": notes}).
        """
        # TODO
        raise NotImplementedError
        yield  # makes this a generator

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
