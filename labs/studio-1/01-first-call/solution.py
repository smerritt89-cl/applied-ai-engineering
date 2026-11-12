"""Lab 01, reference solution. Try starter.py first."""
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
    """Stream one reply and return its text, usage, stop reason, and timings."""
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system is not None:
        kwargs["system"] = system

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

    return {
        "text": "".join(chunks),
        "usage": _usage_dict(final.usage),
        "stop_reason": final.stop_reason,
        "model": model,
        "ttft_s": ttft,
        "total_s": total,
    }


def cost_usd(usage: dict[str, int], model: str, prices: dict[str, dict[str, float]] = PRICES) -> float:
    """Price a usage record. Missing fields count as zero; unknown models raise KeyError."""
    p = prices[model]
    return (
        usage.get("input_tokens", 0) * p["input"]
        + usage.get("output_tokens", 0) * p["output"]
        + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]
        + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
    ) / 1_000_000


def require_complete(result: dict[str, Any]) -> str:
    """Return the text only if the model finished; raise otherwise."""
    reason = result["stop_reason"]
    if reason in ("end_turn", "stop_sequence"):
        return result["text"]
    if reason in ("max_tokens", "model_context_window_exceeded"):
        raise TruncatedError(f"response truncated (stop_reason={reason})")
    if reason == "refusal":
        raise RefusalError("model declined; log it, then consider a fallback model or rephrasing")
    raise ValueError(f"unexpected stop_reason for a text reply: {reason}")


def is_retryable(exc: BaseException) -> bool:
    """True for transient failures worth retrying."""
    if isinstance(exc, anthropic.RateLimitError):
        # A 429 with no retry-after is usually the monthly spend cap: retrying cannot help.
        return exc.response.headers.get("retry-after") is not None
    if isinstance(exc, anthropic.InternalServerError):  # 5xx, including 529 overloaded
        return True
    if isinstance(exc, anthropic.APIConnectionError):  # includes APITimeoutError
        return True
    return False


def backoff_delay(
    attempt: int,
    *,
    base: float = 0.5,
    cap: float = 8.0,
    retry_after: float | None = None,
    rng: Callable[[], float] = random.random,
) -> float:
    """Full-jitter exponential backoff, never shorter than retry_after."""
    delay = rng() * min(cap, base * 2**attempt)
    if retry_after is not None:
        delay = max(delay, retry_after)
    return delay


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
    """Call fn(); retry transient SDK errors with backoff; re-raise everything else."""
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 (we re-raise anything not retryable)
            if not is_retryable(exc) or attempt + 1 >= max_attempts:
                raise
            sleep(backoff_delay(attempt, base=base, cap=cap, retry_after=_retry_after_seconds(exc), rng=rng))
    raise AssertionError("unreachable")


if __name__ == "__main__":
    # Disable the SDK's own retries so with_retries is the only retry layer you are observing.
    client = anthropic.Anthropic(max_retries=0)
    result = with_retries(lambda: stream_reply(client, "In two sentences: what is a token, for an LLM?"))
    print(require_complete(result))
    print(result["usage"], f"cost ${cost_usd(result['usage'], result['model']):.6f}",
          f"ttft {result['ttft_s']:.2f}s total {result['total_s']:.2f}s")
