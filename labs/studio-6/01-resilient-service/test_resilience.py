"""Tests for Studio 6 lab 01. Offline tests use a fake model client and a fake clock,
so they need no API key and run in milliseconds. FastAPI tests skip if FastAPI is missing.
Live tests are marked @pytest.mark.live.

Run:  pytest studio-6/01-resilient-service -q
"""
import json
import os
import random

import pytest

import starter as lab


# ----------------------------------------------------------------------------- test doubles


class FakeClock:
    """Time only moves when someone sleeps or the test advances it."""

    def __init__(self, start: float = 1000.0):
        self.t = start
        self.sleeps = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0, "never sleep a negative amount"
        self.sleeps.append(seconds)
        self.t += seconds

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FakeModelClient:
    """Scripted per model. Each script entry is a string (success), an exception (raised),
    or, for streams, a list of chunks where any element may be an exception."""

    def __init__(self, clock=None, script=None, stream_script=None, seconds_per_chunk=0.0):
        self.clock = clock
        self.script = {m: list(v) for m, v in (script or {}).items()}
        self.stream_script = {m: list(v) for m, v in (stream_script or {}).items()}
        self.seconds_per_chunk = seconds_per_chunk
        self.calls = []

    def complete(self, *, model, messages, max_tokens, timeout):
        self.calls.append({"model": model, "timeout": timeout, "kind": "complete"})
        outcome = self.script[model].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def stream(self, *, model, messages, max_tokens, timeout):
        self.calls.append({"model": model, "timeout": timeout, "kind": "stream"})
        chunks = self.stream_script[model].pop(0)
        if isinstance(chunks, Exception):
            raise chunks

        def gen():
            for chunk in chunks:
                if self.clock is not None and self.seconds_per_chunk:
                    self.clock.advance(self.seconds_per_chunk)
                if isinstance(chunk, Exception):
                    raise chunk
                yield chunk

        return gen()


def overloaded(retry_after=None):
    return lab.TransientError("529 overloaded", retry_after=retry_after, status=529)


PRIMARY, FALLBACK = "claude-opus-5-5", "claude-sonnet-5-5"
USER = [{"role": "user", "content": "Summarize the incident report."}]


def make_llm(client, clock, **kw):
    kw.setdefault("policy", lab.RetryPolicy(max_attempts=3, base_delay=0.5, max_delay=8.0, attempt_timeout=30.0))
    return lab.ResilientLLM(client, [PRIMARY, FALLBACK], clock=clock, rng=random.Random(7), **kw)


# ----------------------------------------------------------------------------- 1. backoff


def test_backoff_is_full_jitter_within_a_growing_capped_ceiling():
    policy = lab.RetryPolicy(base_delay=0.5, max_delay=8.0)
    rng = random.Random(0)
    for retry_number, ceiling in [(1, 0.5), (2, 1.0), (3, 2.0), (4, 4.0), (5, 8.0), (9, 8.0)]:
        samples = [policy.backoff_delay(retry_number, rng) for _ in range(400)]
        assert all(0 <= s <= ceiling for s in samples), f"retry {retry_number}: delays must lie in [0, {ceiling}]"
        assert max(samples) > 0.8 * ceiling, f"retry {retry_number}: full jitter should use the whole range"
        assert min(samples) < 0.2 * ceiling, "full jitter starts at zero, not at half the ceiling"


def test_backoff_is_random_not_identical_for_every_client():
    policy = lab.RetryPolicy()
    a = [policy.backoff_delay(3, random.Random(1)) for _ in range(1)]
    b = [policy.backoff_delay(3, random.Random(2)) for _ in range(1)]
    assert a != b, "two clients with different rngs should not retry at the same instant"


# ----------------------------------------------------------------------------- 2. classifying SDK errors


anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")
REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(cls, status, headers=None, body=None):
    return cls("error", response=httpx2.Response(status, request=REQ, headers=headers or {}), body=body)


def test_rate_limit_is_transient_and_keeps_retry_after():
    err = lab.classify_exception(status_error(anthropic.RateLimitError, 429, {"retry-after": "3"}))
    assert isinstance(err, lab.TransientError)
    assert err.retry_after == 3.0


def test_overloaded_and_server_errors_are_transient():
    for status in (500, 529):
        err = lab.classify_exception(status_error(anthropic.InternalServerError, status))
        assert isinstance(err, lab.TransientError), f"{status} should be retryable"


def test_timeouts_and_dropped_connections_are_transient():
    assert isinstance(lab.classify_exception(anthropic.APITimeoutError(request=REQ)), lab.TransientError)
    assert isinstance(lab.classify_exception(anthropic.APIConnectionError(request=REQ)), lab.TransientError)


def test_client_errors_are_permanent():
    assert isinstance(lab.classify_exception(status_error(anthropic.BadRequestError, 400)), lab.PermanentError)
    assert isinstance(lab.classify_exception(status_error(anthropic.AuthenticationError, 401)), lab.PermanentError)


def test_spend_cap_429_is_permanent_even_though_it_is_a_429():
    body = {"type": "error", "error": {"type": "rate_limit_error", "message": "usage limits",
                                       "details": {"error_code": "enforced_spend_limit_reached"}}}
    err = lab.classify_exception(status_error(anthropic.RateLimitError, 429, body=body))
    assert isinstance(err, lab.PermanentError), "the spend-cap 429 keeps failing until the month resets"


# ----------------------------------------------------------------------------- 3. retries


def test_retries_transient_errors_then_succeeds():
    clock = FakeClock()
    outcomes = [overloaded(), overloaded(), "ok"]

    def fn(timeout):
        o = outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o

    policy = lab.RetryPolicy(max_attempts=3)
    assert lab.call_with_retries(fn, policy=policy, clock=clock, rng=random.Random(0)) == "ok"
    assert len(clock.sleeps) == 2, "two failures mean two sleeps"


def test_gives_up_after_max_attempts_and_reraises():
    clock = FakeClock()
    calls = []

    def fn(timeout):
        calls.append(timeout)
        raise overloaded()

    with pytest.raises(lab.TransientError):
        lab.call_with_retries(fn, policy=lab.RetryPolicy(max_attempts=4), clock=clock, rng=random.Random(0))
    assert len(calls) == 4, "max_attempts counts the first call"
    assert len(clock.sleeps) == 3, "no sleep after the final attempt"


def test_permanent_errors_and_refusals_are_not_retried():
    for exc in (lab.PermanentError("400"), lab.Refused("cyber")):
        calls = []

        def fn(timeout, exc=exc):
            calls.append(1)
            raise exc

        with pytest.raises(type(exc)):
            lab.call_with_retries(fn, policy=lab.RetryPolicy(max_attempts=5), clock=FakeClock(), rng=random.Random(0))
        assert len(calls) == 1, f"{type(exc).__name__} must not be retried"


def test_honors_retry_after_as_a_minimum_wait():
    clock = FakeClock()
    outcomes = [overloaded(retry_after=5.0), "ok"]

    def fn(timeout):
        o = outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o

    lab.call_with_retries(fn, policy=lab.RetryPolicy(base_delay=0.1), clock=clock, rng=random.Random(0))
    assert clock.sleeps[0] >= 5.0, "wait at least as long as retry-after says"


def test_deadline_bounds_attempt_timeouts_and_stops_retrying():
    clock = FakeClock()
    timeouts = []

    def fn(timeout):
        timeouts.append(timeout)
        clock.advance(timeout)  # the call hangs until its timeout fires
        raise lab.TransientError("timed out")

    policy = lab.RetryPolicy(max_attempts=10, base_delay=0.5, attempt_timeout=30.0)
    deadline = clock.now() + 45.0
    with pytest.raises(lab.TransientError):
        lab.call_with_retries(fn, policy=policy, clock=clock, rng=random.Random(0), deadline=deadline)
    assert timeouts[0] == 30.0, "first attempt gets the full per-attempt timeout"
    assert timeouts[1] <= 15.0, "later attempts get only what is left of the deadline"
    assert clock.now() <= deadline + 1e-9, "never run past the deadline"


# ----------------------------------------------------------------------------- 4. circuit breaker


def test_breaker_opens_after_consecutive_failures_and_rejects_fast():
    clock = FakeClock()
    br = lab.CircuitBreaker(failure_threshold=3, reset_timeout=30.0, clock=clock)
    for _ in range(3):
        assert br.allow()
        br.record_failure()
    assert br.state == "open"
    assert not br.allow(), "an open breaker rejects without calling the service"


def test_success_resets_the_failure_count():
    br = lab.CircuitBreaker(failure_threshold=3, clock=FakeClock())
    br.record_failure()
    br.record_failure()
    br.record_success()
    br.record_failure()
    br.record_failure()
    assert br.state == "closed", "only consecutive failures should trip the breaker"


def test_half_open_allows_exactly_one_trial():
    clock = FakeClock()
    br = lab.CircuitBreaker(failure_threshold=1, reset_timeout=30.0, clock=clock)
    br.record_failure()
    clock.advance(29.9)
    assert not br.allow()
    clock.advance(0.2)
    assert br.state == "half_open"
    assert br.allow(), "the first caller after the reset timeout gets a trial"
    assert not br.allow(), "everyone else waits while the trial is in flight"


def test_trial_success_closes_and_trial_failure_reopens():
    clock = FakeClock()
    br = lab.CircuitBreaker(failure_threshold=1, reset_timeout=10.0, clock=clock)
    br.record_failure()
    clock.advance(10)
    assert br.allow()
    br.record_failure()
    assert br.state == "open", "a failed trial reopens the breaker"
    clock.advance(5)
    assert not br.allow(), "and the reset timer starts again from the failed trial"
    clock.advance(5)
    assert br.allow()
    br.record_success()
    assert br.state == "closed" and br.allow()


# ----------------------------------------------------------------------------- 5. complete(): fallbacks and degradation


def test_primary_success_uses_primary():
    clock = FakeClock()
    client = FakeModelClient(script={PRIMARY: ["hello"]})
    reply = make_llm(client, clock).complete(USER)
    assert (reply.text, reply.model, reply.degraded) == ("hello", PRIMARY, False)


def test_overloaded_primary_falls_back_after_retries():
    clock = FakeClock()
    client = FakeModelClient(script={PRIMARY: [overloaded()] * 3, FALLBACK: ["from sonnet"]})
    reply = make_llm(client, clock).complete(USER)
    assert reply.model == FALLBACK and reply.text == "from sonnet"
    assert [c["model"] for c in client.calls] == [PRIMARY] * 3 + [FALLBACK]
    assert any(PRIMARY in n for n in reply.notes), "record why the fallback was used"


def test_refusal_falls_back_without_counting_as_an_outage():
    clock = FakeClock()
    client = FakeModelClient(script={PRIMARY: [lab.Refused("cyber")], FALLBACK: ["answered"]})
    llm = make_llm(client, clock)
    reply = llm.complete(USER)
    assert reply.model == FALLBACK
    assert len([c for c in client.calls if c["model"] == PRIMARY]) == 1, "never retry a refusal on the same model"
    assert llm.breakers[PRIMARY].failures == 0, "a refusal is not a service failure"


def test_bad_request_raises_and_does_not_fall_back():
    clock = FakeClock()
    client = FakeModelClient(script={PRIMARY: [lab.PermanentError("400 bad request")], FALLBACK: ["nope"]})
    with pytest.raises(lab.PermanentError):
        make_llm(client, clock).complete(USER)
    assert all(c["model"] == PRIMARY for c in client.calls), "a malformed request fails on every model"


def test_everything_down_degrades_gracefully():
    clock = FakeClock()
    client = FakeModelClient(script={PRIMARY: [overloaded()] * 3, FALLBACK: [overloaded()] * 3})
    reply = make_llm(client, clock).complete(USER)
    assert reply.degraded and reply.model is None
    assert reply.text == lab.DEGRADED_MESSAGE


def test_open_breaker_skips_primary_without_calling_it():
    clock = FakeClock()
    client = FakeModelClient(script={PRIMARY: [overloaded()] * 6, FALLBACK: ["a", "b"]})
    breakers = {PRIMARY: lab.CircuitBreaker(failure_threshold=1, reset_timeout=60, clock=clock),
                FALLBACK: lab.CircuitBreaker(failure_threshold=5, reset_timeout=60, clock=clock)}
    llm = make_llm(client, clock, breakers=breakers)
    assert llm.complete(USER).model == FALLBACK  # primary fails 3 times, breaker opens
    calls_before = len(client.calls)
    reply = llm.complete(USER)
    assert reply.model == FALLBACK
    assert [c["model"] for c in client.calls[calls_before:]] == [FALLBACK], "open breaker: fail fast, no call"


def test_one_deadline_covers_the_whole_chain():
    clock = FakeClock()

    class SlowClient(FakeModelClient):
        def complete(self, *, model, messages, max_tokens, timeout):
            self.calls.append({"model": model, "timeout": timeout})
            clock.advance(timeout)
            raise lab.TransientError("timeout")

    client = SlowClient()
    llm = make_llm(client, clock, request_deadline=40.0)
    start = clock.now()
    reply = llm.complete(USER)
    assert reply.degraded
    assert clock.now() - start <= 40.0 + 1e-9, "fallbacks must share the request's time budget, not restart it"


# ----------------------------------------------------------------------------- 6. streaming


def events_of(llm):
    return list(llm.stream_events(USER))


def test_stream_happy_path():
    clock = FakeClock()
    client = FakeModelClient(clock, stream_script={PRIMARY: [["Hel", "lo"]]})
    ev = events_of(make_llm(client, clock))
    assert [e for e, _ in ev] == ["meta", "delta", "delta", "done"]
    assert ev[0][1]["model"] == PRIMARY
    assert "".join(d["text"] for e, d in ev if e == "delta") == "Hello"


def test_stream_failure_before_first_token_falls_back():
    clock = FakeClock()
    client = FakeModelClient(
        clock, stream_script={PRIMARY: [[overloaded()]] * 3, FALLBACK: [["from ", "sonnet"]]}
    )
    ev = events_of(make_llm(client, clock))
    assert ev[0] == ("meta", ev[0][1]) and ev[0][1]["model"] == FALLBACK
    assert ev[-1][0] == "done"


def test_stream_failure_after_first_token_does_not_switch_models():
    clock = FakeClock()
    client = FakeModelClient(clock, stream_script={PRIMARY: [["The answer ", overloaded()]], FALLBACK: [["x"]]})
    ev = events_of(make_llm(client, clock))
    names = [e for e, _ in ev]
    assert names == ["meta", "delta", "error"], "once text reached the user, report the error instead of restarting"
    assert ev[-1][1]["type"] == "interrupted"
    assert not any(c["model"] == FALLBACK for c in client.calls)


def test_mid_stream_refusal_tells_the_client_to_discard_partial_text():
    clock = FakeClock()
    client = FakeModelClient(clock, stream_script={PRIMARY: [["Step one", lab.Refused("cyber")]]})
    ev = events_of(make_llm(client, clock))
    assert ev[-1][0] == "error" and ev[-1][1]["type"] == "refusal"
    assert ev[-1][1]["discard_partial"] is True


def test_stream_enforces_the_total_deadline():
    clock = FakeClock()
    client = FakeModelClient(clock, stream_script={PRIMARY: [["tok"] * 100]}, seconds_per_chunk=1.0)
    ev = events_of(make_llm(client, clock, request_deadline=10.0))
    assert ev[-1][0] == "error" and ev[-1][1]["type"] == "deadline"
    assert sum(1 for e, _ in ev if e == "delta") <= 11, "stop streaming once the total budget is spent"


def test_stream_degrades_when_all_models_are_down():
    clock = FakeClock()
    client = FakeModelClient(clock, stream_script={PRIMARY: [overloaded()] * 3, FALLBACK: [overloaded()] * 3})
    ev = events_of(make_llm(client, clock))
    assert ev[-1][0] == "degraded"


def test_format_sse():
    assert lab.format_sse("delta", {"text": "hi"}) == 'event: delta\ndata: {"text": "hi"}\n\n'


# ----------------------------------------------------------------------------- 7. HTTP layer (optional)


def _app_client(llm):
    pytest.importorskip("fastapi")
    testclient = pytest.importorskip("fastapi.testclient")
    return testclient.TestClient(lab.create_app(llm))


def test_http_chat_and_health():
    clock = FakeClock()
    http = _app_client(make_llm(FakeModelClient(script={PRIMARY: ["pong"]}), clock))
    r = http.post("/chat", json={"message": "ping"})
    assert r.status_code == 200 and r.json()["text"] == "pong" and r.json()["degraded"] is False
    assert http.get("/healthz").json()["breakers"][PRIMARY] == "closed"
    assert http.post("/chat", json={"message": ""}).status_code == 422, "validate input at the edge"


def test_http_stream_is_server_sent_events():
    clock = FakeClock()
    http = _app_client(make_llm(FakeModelClient(clock, stream_script={PRIMARY: [["a", "b"]]}), clock))
    r = http.post("/chat/stream", json={"message": "hi"})
    assert r.headers["content-type"].startswith("text/event-stream")
    events = [block for block in r.text.split("\n\n") if block]
    assert events[0].startswith("event: meta") and events[-1].startswith("event: done")
    data = [json.loads(b.split("data: ", 1)[1]) for b in events if b.startswith("event: delta")]
    assert "".join(d["text"] for d in data) == "ab"


# ----------------------------------------------------------------------------- 8. live (costs a fraction of a cent)


@pytest.mark.live
def test_live_complete_and_stream():
    client = lab.AnthropicModelClient()
    llm = lab.ResilientLLM(client, ["claude-haiku-5-5"], request_deadline=60.0, max_tokens=64)
    reply = llm.complete([{"role": "user", "content": "Reply with the single word: ready"}])
    print(reply)
    assert not reply.degraded and "ready" in reply.text.lower()
    ev = list(llm.stream_events([{"role": "user", "content": "Count from 1 to 5, separated by spaces."}]))
    print(ev)
    assert ev[-1][0] == "done"
