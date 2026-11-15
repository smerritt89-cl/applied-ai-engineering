"""Acceptance tests for CHANGE.md (Studio 5 lab 02): due_phrase must be copied from the source.

Run:  pytest studio-5/02-sft-dataset/test_change.py -q
"""
from __future__ import annotations

import copy
import json
import pathlib
from collections import Counter
from types import SimpleNamespace

import pytest

import starter as lab

pytestmark = pytest.mark.change

DATA = pathlib.Path(__file__).parent / "data"


def item(**overrides) -> dict:
    base = {
        "task": "Send the revised budget",
        "owner": "Priya",
        "owner_missing_reason": None,
        "due_date": None,
        "due_phrase": "by Friday",
        "priority": "medium",
        "evidence": "I'll send the revised budget by Friday.",
    }
    base.update(overrides)
    return base


def record(rid="x1", text="Priya: I'll send the revised budget by Friday.", items=None, **extra) -> dict:
    r = {"id": rid, "kind": "meeting", "thread": f"th-{rid}", "text": text,
         "label": {"items": [item()] if items is None else items}}
    r.update(extra)
    return r


def test_invented_due_phrase_is_caught():
    r = record(items=[item(due_phrase="by November 21")])
    assert lab.validate_record(r) == ["item 0: due_phrase not found in source"]


def test_due_phrase_matching_ignores_line_wrapping():
    r = record(text="Priya: I'll send the revised budget by\n   Friday.", items=[item(due_phrase="by  Friday")])
    assert lab.validate_record(r) == [], "compare after normalize_ws, like evidence and owner"


def test_null_due_phrase_is_fine():
    assert lab.validate_record(record(items=[item(due_phrase=None)])) == []


def test_problem_order_is_evidence_then_owner_then_due_phrase():
    r = record(items=[item(evidence="Priya promised the budget soon.", owner="Omar", due_phrase="next week")])
    assert lab.validate_record(r) == [
        "item 0: evidence not found in source",
        "item 0: owner not found in source",
        "item 0: due_phrase not found in source",
    ]


def test_each_item_is_numbered():
    text = "Priya: I'll send the revised budget by Friday. Omar: I'll book the room."
    good = item()
    bad = item(task="Book the room", owner="Omar", due_phrase="tomorrow", evidence="I'll book the room.")
    assert lab.validate_record(record(text=text, items=[good, bad])) == ["item 1: due_phrase not found in source"]


def test_schema_errors_still_stop_before_content_checks():
    r = record(items=[item(priority="urgent", due_phrase="never said")])
    problems = lab.validate_record(r)
    assert problems and all(p.startswith("schema:") for p in problems)


def test_real_data_is_unchanged():
    records = lab.load_jsonl(DATA / "sources.jsonl")
    bad = {r["id"] for r in records if lab.validate_record(r)}
    assert bad == {"e12", "t12", "m12"}, "every due_phrase in the shipped data is verbatim, so nothing new is quarantined"
