"""Acceptance tests for this lab's CHANGE.md task: one bad call must not crash a judge run.

Run:  pytest studio-3/02-judge-calibration/test_change.py -q
"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace

import anthropic
import pytest

import starter as lab

pytestmark = pytest.mark.change

DATA = pathlib.Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def examples():
    return lab.load_examples(DATA / "labeled.jsonl")


def connection_error():
    # A real SDK exception, built offline. The SDK normally attaches the HTTP request; the tests don't need one.
    return anthropic.APIConnectionError(message="Connection error.", request=None)


class ScriptedMessages:
    """Fake client.messages: each parse() call returns or raises the next scripted item."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def parse(self, **kwargs):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def client_with(*script):
    return SimpleNamespace(messages=ScriptedMessages(script))


def ok(verdict):
    return SimpleNamespace(stop_reason="end_turn", parsed_output=lab.Verdict(critique="Rule 2 supports it.", verdict=verdict))


def test_missing_parse_is_invalid_not_a_crash(examples):
    result = lab.judge(client_with(SimpleNamespace(stop_reason="end_turn", parsed_output=None)), examples[0], "P")
    assert result.status == "invalid"
    assert result.verdict is None


def test_api_error_is_recorded_with_its_message(examples):
    result = lab.judge(client_with(connection_error()), examples[0], "P")
    assert result.status == "error"
    assert result.verdict is None
    assert "Connection error" in result.critique, "keep the error text so you can see what went wrong"


def test_programming_errors_still_raise(examples):
    with pytest.raises(TypeError):
        lab.judge(client_with(TypeError("bug in my code")), examples[0], "P")


def test_run_continues_past_failures_and_scoring_excludes_them(examples):
    three = examples[:3]
    client = client_with(ok(three[0].human_label), connection_error(), SimpleNamespace(stop_reason="end_turn", parsed_output=None))
    verdicts = lab.run_judge(client, three, "P")
    assert client.messages.calls == 3, "every example gets its call even after one fails"
    assert verdicts == {three[0].id: three[0].human_label, three[1].id: None, three[2].id: None}
    m = lab.score_judge(three, verdicts)
    assert m["errors"] == 2 and m["n"] == 1


def test_existing_statuses_unchanged(examples):
    assert lab.judge(client_with(SimpleNamespace(stop_reason="refusal", parsed_output=None)), examples[0], "P").status == "refusal"
    assert lab.judge(client_with(SimpleNamespace(stop_reason="max_tokens", parsed_output=None)), examples[0], "P").status == "truncated"
    good = lab.judge(client_with(ok("pass")), examples[0], "P")
    assert (good.status, good.verdict) == ("ok", "pass")
