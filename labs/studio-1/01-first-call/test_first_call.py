"""Tests for lab 01. Offline tests use a fake client; live tests call the API.

Run: pytest studio-1/01-first-call -q
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import anthropic
import httpx2  # the HTTP library the anthropic SDK (1.x and later) is built on
import pytest

# Every lab has a module named `starter`, so make sure this file imports ITS OWN copy
# even when pytest collects several labs in one run.
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).parent))
for _mod in ("starter", "solution"):
    _sys.modules.pop(_mod, None)

from starter import (
    PRICES,
    RefusalError,
    TruncatedError,
    backoff_delay,
    cost_usd,
    is_retryable,
    require_complete,
    stream_reply,
    with_retries,
)

# --------------------------------------------------------------------------- fakes


class FakeStream:
    def __init__(self, chunks, final, clock):
        self._chunks = chunks
        self._final = final
        self._clock = clock

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        for c in self._chunks:
            self._clock.advance(0.25)  # each chunk "arrives" 0.25 s after the previous one
            yield c

    def get_final_message(self):
        self._clock.advance(0.1)
        return self._final


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class FakeClient:
    """Mimics client.messages.stream(...) closely enough for stream_reply."""

    def __init__(self, chunks, stop_reason="end_turn", usage=None):
        self.clock = FakeClock()
        self.calls = []
        usage = usage or SimpleNamespace(
            input_tokens=12, output_tokens=7, cache_creation_input_tokens=None, cache_read_input_tokens=0
        )
        final = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="".join(chunks))],
            stop_reason=stop_reason,
            usage=usage,
        )
        outer = self

        class _Messages:
            def stream(self, **kwargs):
                outer.calls.append(kwargs)
                return FakeStream(chunks, final, outer.clock)

        self.messages = _Messages()


def _status_error(cls, status, headers=None):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, headers=headers or {}, request=request)
    return cls("simulated", response=response, body={"type": "error", "error": {"type": "x", "message": "simulated"}})


def _connection_error():
    return anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))


# --------------------------------------------------------------------------- stream_reply


def test_stream_reply_collects_text_usage_and_timing():
    client = FakeClient(["Tokens are ", "chunks of text."])
    r = stream_reply(client, "What is a token?", model="claude-haiku-5-5", max_tokens=300, clock=client.clock)
    assert r["text"] == "Tokens are chunks of text."
    assert r["stop_reason"] == "end_turn"
    assert r["model"] == "claude-haiku-5-5"
    assert r["usage"] == {
        "input_tokens": 12,
        "output_tokens": 7,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }, "use _usage_dict(final.usage); None becomes 0"
    assert r["ttft_s"] == pytest.approx(0.25), "TTFT is measured at the first text chunk"
    assert r["total_s"] == pytest.approx(0.6), "total includes every chunk and the final message"


def test_stream_reply_sends_a_well_formed_request():
    client = FakeClient(["ok"])
    stream_reply(client, "hi", model="claude-haiku-5-5", max_tokens=50, clock=client.clock)
    kw = client.calls[0]
    assert kw["model"] == "claude-haiku-5-5"
    assert kw["max_tokens"] == 50
    assert kw["messages"] == [{"role": "user", "content": "hi"}]
    assert "system" not in kw, "omit system when it is None"
    assert "temperature" not in kw, "the current API version rejects sampling parameters"

    client2 = FakeClient(["ok"])
    stream_reply(client2, "hi", system="Be brief.", clock=client2.clock)
    assert client2.calls[0]["system"] == "Be brief.", "system is a top-level field, not a message"


def test_stream_reply_with_no_text_has_no_ttft():
    client = FakeClient([], stop_reason="refusal")
    r = stream_reply(client, "x", clock=client.clock)
    assert r["text"] == "" and r["ttft_s"] is None and r["stop_reason"] == "refusal"


# --------------------------------------------------------------------------- cost_usd


def test_cost_basic():
    u = {"input_tokens": 2000, "output_tokens": 500}
    assert cost_usd(u, "claude-haiku-5-5") == pytest.approx((2000 * 0.10 + 500 * 0.50) / 1e6)


def test_cost_prices_every_usage_field():
    u = {
        "input_tokens": 100,
        "output_tokens": 1000,
        "cache_creation_input_tokens": 10_000,
        "cache_read_input_tokens": 50_000,
    }
    p = PRICES["claude-opus-5-5"]
    expected = (100 * p["input"] + 1000 * p["output"] + 10_000 * p["cache_write"] + 50_000 * p["cache_read"]) / 1e6
    assert cost_usd(u, "claude-opus-5-5") == pytest.approx(expected)


def test_cost_custom_prices_and_unknown_model():
    prices = {"m": {"input": 1.0, "output": 2.0, "cache_write": 0.0, "cache_read": 0.0}}
    assert cost_usd({"input_tokens": 1_000_000, "output_tokens": 1_000_000}, "m", prices) == pytest.approx(3.0)
    with pytest.raises(KeyError):
        cost_usd({"input_tokens": 1}, "not-a-model")


# --------------------------------------------------------------------------- require_complete


@pytest.mark.parametrize("reason", ["end_turn", "stop_sequence"])
def test_require_complete_returns_text(reason):
    assert require_complete({"text": "done", "stop_reason": reason}) == "done"


@pytest.mark.parametrize("reason", ["max_tokens", "model_context_window_exceeded"])
def test_require_complete_flags_truncation(reason):
    with pytest.raises(TruncatedError):
        require_complete({"text": '{"risk": "hi', "stop_reason": reason})


def test_require_complete_flags_refusal_and_unknown():
    with pytest.raises(RefusalError):
        require_complete({"text": "", "stop_reason": "refusal"})
    with pytest.raises(ValueError):
        require_complete({"text": "", "stop_reason": "tool_use"})


# --------------------------------------------------------------------------- retries


def test_is_retryable_classification():
    assert is_retryable(_status_error(anthropic.RateLimitError, 429, {"retry-after": "2"}))
    assert not is_retryable(_status_error(anthropic.RateLimitError, 429)), "429 without retry-after: spend cap"
    assert is_retryable(_status_error(anthropic.InternalServerError, 500))
    assert is_retryable(_status_error(anthropic.InternalServerError, 529)), "529 overloaded is transient"
    assert is_retryable(_connection_error())
    assert not is_retryable(_status_error(anthropic.BadRequestError, 400))
    assert not is_retryable(_status_error(anthropic.AuthenticationError, 401))
    assert not is_retryable(_status_error(anthropic.NotFoundError, 404))
    assert not is_retryable(ValueError("your own bug"))


def test_backoff_delay_math():
    assert backoff_delay(0, rng=lambda: 1.0) == pytest.approx(0.5)
    assert backoff_delay(3, rng=lambda: 1.0) == pytest.approx(4.0)
    assert backoff_delay(10, rng=lambda: 1.0) == pytest.approx(8.0), "cap applies"
    assert backoff_delay(2, rng=lambda: 0.5) == pytest.approx(1.0)
    assert backoff_delay(1, rng=lambda: 0.0, retry_after=3.0) == pytest.approx(3.0)


def test_with_retries_recovers_from_transient_errors():
    errors = [_status_error(anthropic.InternalServerError, 529), _connection_error()]
    sleeps = []

    def flaky():
        if errors:
            raise errors.pop(0)
        return "ok"

    assert with_retries(flaky, sleep=sleeps.append, rng=lambda: 1.0) == "ok"
    assert sleeps == [pytest.approx(0.5), pytest.approx(1.0)], "exponential delays between attempts"


def test_with_retries_honors_retry_after():
    calls = []
    sleeps = []

    def limited():
        calls.append(1)
        if len(calls) == 1:
            raise _status_error(anthropic.RateLimitError, 429, {"retry-after": "5"})
        return "ok"

    assert with_retries(limited, sleep=sleeps.append, rng=lambda: 0.1) == "ok"
    assert sleeps == [pytest.approx(5.0)]


def test_with_retries_fails_fast_on_client_errors():
    calls = []

    def bad():
        calls.append(1)
        raise _status_error(anthropic.BadRequestError, 400)

    with pytest.raises(anthropic.BadRequestError):
        with_retries(bad, sleep=lambda s: None)
    assert len(calls) == 1, "never retry a 400"


def test_with_retries_gives_up_after_max_attempts():
    calls = []

    def down():
        calls.append(1)
        raise _status_error(anthropic.InternalServerError, 500)

    with pytest.raises(anthropic.InternalServerError):
        with_retries(down, max_attempts=3, sleep=lambda s: None)
    assert len(calls) == 3


# --------------------------------------------------------------------------- live (needs ANTHROPIC_API_KEY)


@pytest.mark.live
def test_live_stream_reply():
    client = anthropic.Anthropic()
    r = with_retries(lambda: stream_reply(client, "Reply with exactly: pong", model="claude-haiku-5-5", max_tokens=256))
    assert "pong" in require_complete(r).lower()
    assert r["usage"]["input_tokens"] > 0 and r["usage"]["output_tokens"] > 0
    assert r["ttft_s"] is not None and r["ttft_s"] <= r["total_s"]
    assert cost_usd(r["usage"], "claude-haiku-5-5") < 0.01


@pytest.mark.live
def test_live_truncation_is_detected():
    client = anthropic.Anthropic()
    r = stream_reply(client, "Count from 1 to 500, one number per line.", model="claude-haiku-5-5", max_tokens=20)
    assert r["stop_reason"] == "max_tokens"
    with pytest.raises(TruncatedError):
        require_complete(r)


def test_key_never_hardcoded():
    """A cheap guard: the lab file must not contain anything that looks like a key."""
    here = os.path.dirname(__file__)
    for name in ("starter.py", "solution.py"):
        with open(os.path.join(here, name)) as f:
            assert "sk-ant-" not in f.read(), f"{name} contains what looks like an API key"
