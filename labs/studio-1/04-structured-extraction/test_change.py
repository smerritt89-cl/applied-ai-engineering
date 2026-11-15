"""Acceptance tests for CHANGE.md (lab 04): verify_evidence also checks due_phrase.

Run:  pytest studio-1/04-structured-extraction/test_change.py -q
"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

import starter as lab

pytestmark = pytest.mark.change

SAMPLES = pathlib.Path(__file__).parent / "samples"
SOURCE = (SAMPLES / "vendor_email.txt").read_text()


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


def extraction_of(*items: dict):
    return lab.Extraction.model_validate({"items": list(items)})


def test_invented_due_phrase_is_flagged():
    ex = extraction_of(item(due_phrase="by next Monday"))
    flags = lab.verify_evidence(ex, SOURCE)
    assert len(flags) == 1
    assert flags[0].problems == ["due_phrase not found in source"]


def test_due_phrase_across_a_line_break_passes():
    # In the email this phrase wraps after "once the". Whitespace must be normalized,
    # exactly as it is for evidence.
    ex = extraction_of(item(due_phrase="once the\n   repair is done"))
    assert lab.verify_evidence(ex, SOURCE) == []


def test_null_due_phrase_is_not_flagged():
    ex = extraction_of(item(due_phrase=None))
    assert lab.verify_evidence(ex, SOURCE) == []


def test_due_phrase_problem_comes_last():
    ex = extraction_of(item(owner="Jordan Lee", evidence="We promise a refund for every delayed box",
                            due_phrase="by Halloween"))
    (flag,) = lab.verify_evidence(ex, SOURCE)
    assert flag.problems == [
        "evidence not found in source",
        "owner not found in source",
        "due_phrase not found in source",
    ]


def test_extract_reports_due_phrase_flags():
    ex = extraction_of(item(), item(due_phrase="by Halloween"))
    response = SimpleNamespace(stop_reason="end_turn", parsed_output=ex)
    client = SimpleNamespace(messages=SimpleNamespace(parse=lambda **kwargs: response))
    result = lab.extract(client, SOURCE)
    assert [(f.index, f.problems) for f in result.flags] == [(1, ["due_phrase not found in source"])]
