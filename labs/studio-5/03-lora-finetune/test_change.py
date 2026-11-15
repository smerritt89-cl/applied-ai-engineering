"""Acceptance tests for CHANGE.md (Studio 5 lab 03): score whether order ids are grounded in the ticket.

Run:  pytest studio-5/03-lora-finetune/test_change.py -q
"""
from __future__ import annotations

import json
import math
import pathlib
import re

import pytest

import make_lora_data as data_gen
import starter as lab

pytestmark = pytest.mark.change

HERE = pathlib.Path(__file__).parent

TICKET_A = "Every request to the invoice portal returns a 500 error since this morning. Whenever you get a chance."
GOLD_A = {"category": "bug", "priority": "low", "product": "invoice portal", "order_id": None}
TICKET_B = "Part of order ORD-62097 is missing from the package. We need this fixed today."
GOLD_B = {"category": "shipping", "priority": "high", "product": None, "order_id": "ORD-62097"}


def out(**fields) -> str:
    base = {"category": "bug", "priority": "low", "product": "invoice portal", "order_id": None}
    base.update(fields)
    return json.dumps(base)


def test_invented_order_id_is_not_grounded():
    s = lab.score_prediction(out(order_id="chango.500"), GOLD_A, ticket=TICKET_A)
    assert s["grounded"] is False, "the authoring run's invented id must be caught"
    assert s["fields_correct"] == 3 and s["exact"] is False


def test_copied_and_null_order_ids_are_grounded():
    copied = lab.score_prediction(
        json.dumps({"category": "shipping", "priority": "high", "product": None, "order_id": "ORD-62097"}),
        GOLD_B, ticket=TICKET_B)
    assert copied["grounded"] is True and copied["exact"] is True
    assert lab.score_prediction(out(), GOLD_A, ticket=TICKET_A)["grounded"] is True, "null is grounded"


def test_non_string_order_id_is_not_grounded():
    s = lab.score_prediction(out(order_id=62097), GOLD_B, ticket=TICKET_B)
    assert s["grounded"] is False, "a number is not text copied from the ticket (and must not crash)"


def test_invalid_output_is_not_grounded():
    s = lab.score_prediction("Sure! Here is the JSON.", GOLD_A, ticket=TICKET_A)
    assert s == {"valid_json": False, "fields_correct": 0, "exact": False, "grounded": False}


def test_without_ticket_the_result_is_unchanged():
    s = lab.score_prediction(out(), GOLD_A)
    assert s == {"valid_json": True, "fields_correct": 4, "exact": True}, "no ticket, no grounded key"
    bad = lab.score_prediction("[1, 2]", GOLD_A)
    assert bad == {"valid_json": False, "fields_correct": 0, "exact": False}


def test_summarize_reports_grounded_rate_only_when_every_score_has_it():
    scored = [
        lab.score_prediction(out(order_id="chango.500"), GOLD_A, ticket=TICKET_A),
        lab.score_prediction(out(), GOLD_A, ticket=TICKET_A),
        lab.score_prediction("not json", GOLD_A, ticket=TICKET_A),
        lab.score_prediction(out(order_id="ORD-62097"), GOLD_B, ticket=TICKET_B),
    ]
    s = lab.summarize_scores(scored)
    assert math.isclose(s["grounded_rate"], 0.5)
    mixed = scored[:2] + [lab.score_prediction(out(), GOLD_A)]
    assert "grounded_rate" not in lab.summarize_scores(mixed), "a partial check is not reported as a rate"
    plain = [lab.score_prediction(out(), GOLD_A)]
    assert set(lab.summarize_scores(plain)) == {"n", "valid_json_rate", "field_accuracy", "exact_match"}
