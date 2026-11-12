"""Lab 01: your first streaming call, cost, and retries.

Fill in every function marked TODO. Run the offline tests with:
    pytest studio-1/01-first-call -q
Helpers whose names start with an underscore are provided; you do not need to change them.
"""
from __future__ import annotations

import random
import time
from typing import Any, Callable

import anthropic

DEFAULT_MODEL = "claude-haiku-5-5"  # cheapest current tier: good for a first call

# USD per million tokens. Snapshot 2026-11-11 from
# https://platform.claude.com/docs/en/about-claude/pricing (check before relying on it).
PRICES: dict[str, dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.10},
    # Haiku 5.5 prices for prompts up to 100,000 tokens; longer prompts cost more.
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_write": 0.125, "cache_read": 0.01},
}

USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


class TruncatedError(Exception):
    """The model stopped because it hit a length limit; the text is incomplete."""


class RefusalError(Exception):
    """The model declined to answer (stop_reason == "refusal")."""


def _usage_dict(usage: Any) -> dict[str, int]:
    return {f: int(getattr(usage, f, 0) or 0) for f in USAGE_FIELDS}


def stream_reply(
    client: Any,
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 2048,
    system: str | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Stream one reply and return its text, usage, stop reason, and timings.

    Use the official SDK's stream helper:
        with client.messages.stream(model=..., max_tokens=..., messages=[...]) as stream:
            for text in stream.text_stream: ...
            final = stream.get_final_message()
    Only pass `system=` when it is not None.

    Return a dict with keys:
        text         all streamed text joined together
        usage        _usage_dict(final.usage)
        stop_reason  final.stop_reason
        model        the model you requested
        ttft_s       seconds from start until the FIRST text chunk (None if no text arrived)
        total_s      seconds from start until the stream finished
    Measure time with `clock()` (injected so tests are deterministic).
    """
    # TODO: implement (README step 1)
    raise NotImplementedError


def cost_usd(usage: dict[str, int], model: str, prices: dict[str, dict[str, float]] = PRICES) -> float:
    """Price a usage record in USD.

    usage has any of: input_tokens, output_tokens, cache_creation_input_tokens,
    cache_read_input_tokens. Missing fields count as zero. Each is priced at its own
    rate from prices[model] ("input", "output", "cache_write", "cache_read"), all
    per million tokens. Unknown models raise KeyError.
    """
    # TODO: implement (README step 2)
    raise NotImplementedError


def require_complete(result: dict[str, Any]) -> str:
    """Return result["text"] only if the model finished.

    end_turn or stop_sequence            -> return the text
    max_tokens or model_context_window_exceeded -> raise TruncatedError
    refusal                              -> raise RefusalError
    anything else                        -> raise ValueError
    """
    # TODO: implement (README step 3)
    raise NotImplementedError


def is_retryable(exc: BaseException) -> bool:
    """True for transient failures worth retrying.

    Retry: anthropic.InternalServerError (5xx, including 529 overloaded),
           anthropic.APIConnectionError (includes timeouts),
           anthropic.RateLimitError ONLY if exc.response.headers has "retry-after"
           (a 429 without it is usually the monthly spend cap).
    Do not retry anything else (400, 401, 403, 404, your own bugs, ...).
    """
    # TODO: implement (README step 4)
    raise NotImplementedError


def backoff_delay(
    attempt: int,
    *,
    base: float = 0.5,
    cap: float = 8.0,
    retry_after: float | None = None,
    rng: Callable[[], float] = random.random,
) -> float:
    """Full-jitter exponential backoff.

    delay = rng() * min(cap, base * 2**attempt), where attempt counts from 0.
    If retry_after is given (seconds), return max(delay, retry_after).
    """
    # TODO: implement (README step 4)
    raise NotImplementedError


def _retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def with_retries(
    fn: Callable[[], Any],
    *,
    max_attempts: int = 4,
    base: float = 0.5,
    cap: float = 8.0,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
) -> Any:
    """Call fn() and return its result, retrying transient failures.

    - Make at most max_attempts calls in total.
    - If fn raises and is_retryable(exc) is False, re-raise immediately.
    - If it is retryable and attempts remain, sleep(backoff_delay(attempt, ...,
      retry_after=_retry_after_seconds(exc), rng=rng)) and try again.
    - After the last attempt, re-raise the last exception.
    """
    # TODO: implement (README step 5)
    raise NotImplementedError


if __name__ == "__main__":
    # Disable the SDK's own retries so with_retries is the only retry layer you are observing.
    client = anthropic.Anthropic(max_retries=0)
    result = with_retries(lambda: stream_reply(client, "In two sentences: what is a token, for an LLM?"))
    print(require_complete(result))
    print(result["usage"], f"cost ${cost_usd(result['usage'], result['model']):.6f}",
          f"ttft {result['ttft_s']:.2f}s total {result['total_s']:.2f}s")
