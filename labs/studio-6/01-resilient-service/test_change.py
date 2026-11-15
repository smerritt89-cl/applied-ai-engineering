"""Acceptance tests for CHANGE.md: a deadline that runs out before a model is called
must not count against that model's circuit breaker.

Run on their own, once you've made the change in work.py:
    pytest studio-6/01-resilient-service/test_change.py -q
"""
import json
import os
import random

import pytest

import starter as lab

pytestmark = pytest.mark.change

PRIMARY, FALLBACK = "claude-opus-5-5", "claude-sonnet-5-5"
USER = [{"role": "user", "content": "Summarize the incident report."}]


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.t = start

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.t += seconds

    def advance(self, seconds: float) -> None:
        self.t += seconds


class HangingPrimary:
    """The primary hangs until each timeout fires; the fallback would answer instantly."""

    def __init__(self, clock):
        self.clock = clock
        self.calls = []

    def _hang_or_answer(self, model, timeout):
        self.calls.append(model)
        if model == PRIMARY:
            self.clock.advance(timeout)
            raise lab.TransientError("timed out")

    def complete(self, *, model, messages, max_tokens, timeout):
        self._hang_or_answer(model, timeout)
        return "from sonnet"

    def stream(self, *, model, messages, max_tokens, timeout):
        self._hang_or_answer(model, timeout)
        return iter(["from ", "sonnet"])


def make_llm(clock, breakers=None):
    policy = lab.RetryPolicy(max_attempts=3, base_delay=0.5, max_delay=8.0, attempt_timeout=30.0)
    client = HangingPrimary(clock)
    llm = lab.ResilientLLM(client, [PRIMARY, FALLBACK], clock=clock, rng=random.Random(7), policy=policy,
                           breakers=breakers, request_deadline=40.0)
    return llm, client


def test_complete_leaves_the_uncalled_fallback_breaker_alone():
    clock = FakeClock()
    llm, client = make_llm(clock)
    reply = llm.complete(USER)
    assert reply.degraded, "the whole budget went to the primary, so the reply is still degraded"
    assert FALLBACK not in client.calls, "the fallback was never called"
    assert llm.breakers[FALLBACK].failures == 0, "an uncalled model must not get a breaker failure"
    assert llm.breakers[PRIMARY].failures == 1, "the primary really did fail, so it still counts"
    assert any(FALLBACK in n and "deadline" in n for n in reply.notes), "say why the fallback was skipped"


def test_stream_leaves_the_uncalled_fallback_breaker_alone():
    clock = FakeClock()
    llm, client = make_llm(clock)
    events = list(llm.stream_events(USER))
    assert events[-1][0] == "degraded"
    assert llm.breakers[FALLBACK].failures == 0
    assert any(FALLBACK in n and "deadline" in n for n in events[-1][1]["notes"])


def test_repeated_slow_primaries_cannot_trip_a_healthy_fallback():
    clock = FakeClock()
    breakers = {PRIMARY: lab.CircuitBreaker(failure_threshold=100, reset_timeout=60, clock=clock),
                FALLBACK: lab.CircuitBreaker(failure_threshold=2, reset_timeout=60, clock=clock)}
    llm, _ = make_llm(clock, breakers=breakers)
    for _ in range(3):
        llm.complete(USER)
    assert llm.breakers[FALLBACK].state == "closed", "the fallback never failed, so it must stay available"


def test_unused_half_open_trial_is_given_back():
    clock = FakeClock()
    fallback_breaker = lab.CircuitBreaker(failure_threshold=1, reset_timeout=10, clock=clock)
    fallback_breaker.record_failure()
    clock.advance(11)
    assert fallback_breaker.state == "half_open"
    breakers = {PRIMARY: lab.CircuitBreaker(failure_threshold=100, reset_timeout=60, clock=clock),
                FALLBACK: fallback_breaker}
    llm, _ = make_llm(clock, breakers=breakers)
    llm.complete(USER)
    assert fallback_breaker.state == "half_open", "no trial call happened, so the breaker should not reopen"
    assert fallback_breaker.allow(), "and the next request should still get the trial"
