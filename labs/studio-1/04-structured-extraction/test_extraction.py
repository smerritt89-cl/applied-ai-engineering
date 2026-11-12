"""Tests for lab 04. Offline tests need no API key; @pytest.mark.live tests call Claude.

Run:  pytest studio-1/04-structured-extraction -q
"""
from __future__ import annotations

import pathlib
from datetime import date
from types import SimpleNamespace

import pydantic
import pytest

import starter as lab

SAMPLES = pathlib.Path(__file__).parent / "samples"


def item(**overrides) -> dict:
    base = {
        "task": "Send the revised ship date",
        "owner": "Dana Whitfield",
        "owner_missing_reason": None,
        "due_date": None,
        "due_phrase": "by end of day Thursday",
        "priority": "high",
        "evidence": "I will send you a revised ship date for the inserts by end of day Thursday, once the repair is done.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- 1. models


def test_valid_item_parses_with_real_types():
    parsed = lab.ActionItem.model_validate(item(due_date="2026-12-03"))
    assert parsed.due_date == date(2026, 12, 3), "due_date should be a datetime.date, not a string"
    assert parsed.priority == "high"


def test_rejects_unknown_fields():
    with pytest.raises(pydantic.ValidationError):
        lab.ActionItem.model_validate(item(assignee="Dana"))


def test_rejects_priority_outside_enum():
    with pytest.raises(pydantic.ValidationError):
        lab.ActionItem.model_validate(item(priority="urgent"))


def test_owner_is_required_but_nullable():
    data = item()
    del data["owner"]
    with pytest.raises(pydantic.ValidationError):
        lab.ActionItem.model_validate(data)
    ok = lab.ActionItem.model_validate(item(owner=None, owner_missing_reason="addressed to the customer's team"))
    assert ok.owner is None


def test_null_owner_needs_a_reason():
    with pytest.raises(pydantic.ValidationError):
        lab.ActionItem.model_validate(item(owner=None, owner_missing_reason=None))


def test_evidence_and_task_cannot_be_trivial():
    with pytest.raises(pydantic.ValidationError):
        lab.ActionItem.model_validate(item(evidence=""))
    with pytest.raises(pydantic.ValidationError):
        lab.ActionItem.model_validate(item(task=""))


def test_schema_is_closed_and_described():
    schema = lab.ActionItem.model_json_schema()
    assert schema.get("additionalProperties") is False, "forbid extra fields"
    expected = {"task", "owner", "owner_missing_reason", "due_date", "due_phrase", "priority", "evidence"}
    assert set(schema["properties"]) == expected
    missing = [name for name, prop in schema["properties"].items() if not prop.get("description")]
    assert not missing, f"every field needs a description (the model reads them): {missing}"
    outer = lab.Extraction.model_json_schema()
    assert outer.get("additionalProperties") is False
    assert outer["required"] == ["items"]


# ---------------------------------------------------------------- 2. verification


SOURCE = (SAMPLES / "vendor_email.txt").read_text()


def extraction_of(*items: dict):
    return lab.Extraction.model_validate({"items": list(items)})


def test_normalize_collapses_whitespace():
    assert lab.normalize("  a \n b\t\tc  ") == "a b c"


def test_verbatim_quote_across_a_line_break_passes():
    # In the email this sentence wraps after "once the".
    ex = extraction_of(item())
    assert lab.verify_evidence(ex, SOURCE) == []


def test_paraphrased_quote_is_flagged():
    ex = extraction_of(item(), item(evidence="Dana will send a new ship date for the inserts on Thursday"))
    flags = lab.verify_evidence(ex, SOURCE)
    assert [f.index for f in flags] == [1]
    assert flags[0].problems == ["evidence not found in source"]


def test_invented_owner_is_flagged():
    ex = extraction_of(item(owner="Jordan Lee"))
    flags = lab.verify_evidence(ex, SOURCE)
    assert len(flags) == 1 and flags[0].problems == ["owner not found in source"]


def test_flag_reports_task_and_all_problems():
    ex = extraction_of(item(owner="Jordan Lee", evidence="We promise a refund for every delayed box"))
    (flag,) = lab.verify_evidence(ex, SOURCE)
    assert flag.task == "Send the revised ship date"
    assert flag.problems == ["evidence not found in source", "owner not found in source"]


# ---------------------------------------------------------------- 3. the call, with a fake client


class _Probe(pydantic.BaseModel):
    x: int


def semantic_error() -> pydantic.ValidationError:
    """A ValidationError of the kind parse() raises when a field fails a client-side check."""
    try:
        _Probe.model_validate({"x": "not a number"})
    except pydantic.ValidationError as err:
        return err
    raise AssertionError("unreachable")


def json_error() -> pydantic.ValidationError:
    """A ValidationError for broken JSON, as when output is truncated."""
    try:
        _Probe.model_validate_json('{"x": 1')
    except pydantic.ValidationError as err:
        return err
    raise AssertionError("unreachable")


class FakeMessages:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        # Copy the messages list so later mutation by the caller can't hide what was sent.
        self.calls.append({**kwargs, "messages": list(kwargs.get("messages", []))})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def create(self, **kwargs):
        raise AssertionError("use client.messages.parse() with output_format, not create()")


class FakeClient:
    def __init__(self, *outcomes):
        self.messages = FakeMessages(outcomes)


def ok_response(extraction, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=extraction)


def test_build_messages_has_document_and_no_prefill():
    msgs = lab.build_messages("hello doc")
    assert msgs[-1]["role"] == "user", "the last message must be from the user (assistant prefill is rejected)"
    assert "hello doc" in str(msgs[-1]["content"])


def test_happy_path_makes_one_parse_call_with_the_model():
    ex = extraction_of(item())
    client = FakeClient(ok_response(ex))
    result = lab.extract(client, SOURCE)
    assert len(client.messages.calls) == 1
    call = client.messages.calls[0]
    assert call["output_format"] is lab.Extraction, "pass the Pydantic class as output_format"
    assert call["model"] == lab.MODEL
    assert call["max_tokens"] >= 1024
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in call, f"{banned} is rejected on the current API version"
    assert result.attempts == 1
    assert result.extraction is ex
    assert result.flags == []


def test_flags_are_computed_on_success():
    ex = extraction_of(item(owner="Jordan Lee"))
    result = lab.extract(FakeClient(ok_response(ex)), SOURCE)
    assert [f.problems for f in result.flags] == [["owner not found in source"]]


def test_retries_once_and_feeds_the_error_back():
    ex = extraction_of(item())
    client = FakeClient(semantic_error(), ok_response(ex))
    result = lab.extract(client, SOURCE)
    assert result.attempts == 2
    first, second = client.messages.calls
    assert len(second["messages"]) == len(first["messages"]) + 1, "append one message describing the errors"
    feedback = second["messages"][-1]
    assert feedback["role"] == "user"
    assert "x:" in str(feedback["content"]), "include each error as '<field>: <message>'"


def test_gives_up_after_the_second_failure():
    client = FakeClient(semantic_error(), semantic_error())
    with pytest.raises(lab.ExtractionFailed):
        lab.extract(client, SOURCE)
    assert len(client.messages.calls) == 2, "retry exactly once"


def test_broken_json_is_not_retried():
    client = FakeClient(json_error())
    with pytest.raises(lab.ExtractionFailed):
        lab.extract(client, SOURCE)
    assert len(client.messages.calls) == 1, "invalid JSON under constrained decoding means truncation or refusal"


@pytest.mark.parametrize("reason", ["refusal", "max_tokens"])
def test_bad_stop_reasons_fail_without_retry(reason):
    client = FakeClient(ok_response(extraction_of(item()), stop_reason=reason))
    with pytest.raises(lab.ExtractionFailed):
        lab.extract(client, SOURCE)
    assert len(client.messages.calls) == 1


# ---------------------------------------------------------------- 4. live


@pytest.mark.live
@pytest.mark.parametrize("name", ["vendor_email.txt", "support_ticket.txt"])
def test_live_extraction(name):
    import anthropic

    document = (SAMPLES / name).read_text()
    result = lab.extract(anthropic.Anthropic(), document)
    items = result.extraction.items
    assert items, "both samples contain action items"
    verified = len(items) - len(result.flags)
    print(f"\n{name}: {len(items)} items, {verified} verified, {len(result.flags)} flagged, {result.attempts} attempt(s)")
    for f in result.flags:
        print("  FLAG", f.index, f.task, f.problems)
    assert verified >= 1, "at least one item should have a verbatim quote"
