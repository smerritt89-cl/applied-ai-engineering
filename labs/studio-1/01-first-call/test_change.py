"""Acceptance tests for CHANGE.md: an on_retry callback for with_retries.

Run on their own, once you've made the change in work.py:
    pytest studio-1/01-first-call/test_change.py -q
"""
from __future__ import annotations

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

from starter import with_retries

pytestmark = pytest.mark.change


def _status_error(cls, status, headers=None):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, headers=headers or {}, request=request)
    return cls("simulated", response=response, body={"type": "error", "error": {"type": "x", "message": "simulated"}})


def _connection_error():
    return anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))


def _flaky(errors, result="ok"):
    """A function that raises each error in turn, then returns result."""
    errors = list(errors)

    def fn():
        if errors:
            raise errors.pop(0)
        return result

    return fn


def test_on_retry_receives_attempt_exception_and_delay():
    e1 = _status_error(anthropic.InternalServerError, 529)
    e2 = _connection_error()
    seen, sleeps = [], []
    out = with_retries(
        _flaky([e1, e2]),
        sleep=sleeps.append,
        rng=lambda: 1.0,
        on_retry=lambda attempt, exc, delay: seen.append((attempt, exc, delay)),
    )
    assert out == "ok"
    assert [(a, d) for a, _, d in seen] == [(0, pytest.approx(0.5)), (1, pytest.approx(1.0))]
    assert seen[0][1] is e1 and seen[1][1] is e2, "pass the exception that caused the retry"
    assert sleeps == [d for _, _, d in seen], "the delay reported is the delay actually slept"


def test_on_retry_reports_the_retry_after_floor():
    seen, sleeps = [], []
    limited = _flaky([_status_error(anthropic.RateLimitError, 429, {"retry-after": "5"})])
    with_retries(limited, sleep=sleeps.append, rng=lambda: 0.1,
                 on_retry=lambda attempt, exc, delay: seen.append(delay))
    assert seen == [pytest.approx(5.0)] and sleeps == [pytest.approx(5.0)]


def test_on_retry_is_called_before_sleeping():
    events = []
    with_retries(
        _flaky([_status_error(anthropic.InternalServerError, 500)]),
        sleep=lambda s: events.append("sleep"),
        rng=lambda: 1.0,
        on_retry=lambda attempt, exc, delay: events.append("on_retry"),
    )
    assert events == ["on_retry", "sleep"]


def test_on_retry_not_called_on_success_or_client_errors():
    seen = []
    record = lambda attempt, exc, delay: seen.append(attempt)  # noqa: E731
    assert with_retries(lambda: "ok", sleep=lambda s: None, on_retry=record) == "ok"
    with pytest.raises(anthropic.BadRequestError):
        with_retries(_flaky([_status_error(anthropic.BadRequestError, 400)]), sleep=lambda s: None, on_retry=record)
    assert seen == [], "no retry happened, so on_retry must not be called"


def test_on_retry_not_called_after_the_last_attempt():
    seen, calls = [], []

    def down():
        calls.append(1)
        raise _status_error(anthropic.InternalServerError, 500)

    with pytest.raises(anthropic.InternalServerError):
        with_retries(down, max_attempts=3, sleep=lambda s: None, rng=lambda: 1.0,
                     on_retry=lambda attempt, exc, delay: seen.append(attempt))
    assert len(calls) == 3
    assert seen == [0, 1], "three attempts means two retries; the final failure is raised, not retried"
