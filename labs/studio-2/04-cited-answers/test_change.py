"""Acceptance tests for CHANGE.md (Studio 2 lab 04): flag claims that cite an archived source.

Run:  pytest studio-2/04-cited-answers/test_change.py -q
All offline: fixtures only, no API key, no network.
"""
from __future__ import annotations

import json
import pathlib

import pytest

import starter as lab

pytestmark = pytest.mark.change

HERE = pathlib.Path(__file__).parent
FIXTURES = HERE / "fixtures"
ARCHIVED = {"faq-020"}


def fixture(name: str):
    path = FIXTURES / name
    return json.loads(path.read_text()) if path.suffix == ".json" else path.read_text()


@pytest.fixture
def passages():
    return lab.load_passages()


def test_marked_answer_flags_the_archived_faq_as_stale(passages):
    answer = lab.parse_marked_answer(fixture("marked_answer.txt"))
    report = lab.verify_answer(answer, passages, archived=ARCHIVED)
    assert report.stale == [0], "claim 0 quotes the archived 2023 FAQ"
    assert [(p.claim_index, p.kind) for p in report.problems] == [(2, "quote not in passage")], (
        "stale is a warning: the problems list is exactly what it was before"
    )
    assert report.uncited == [3]


def test_stale_is_a_warning_not_a_problem(passages):
    quote = "any flight over 4 hours may be booked in business class without approval"
    answer = lab.CitedAnswer(claims=[lab.Claim("Business class over 4 hours.", [lab.Citation("faq-020", quote)])])
    report = lab.verify_answer(answer, passages, archived=ARCHIVED)
    assert report.stale == [0]
    assert report.ok, "a verbatim quote from an archived passage is still a valid citation"
    assert report.cited_claims == 1


def test_each_claim_is_listed_once(passages):
    q1 = "any flight over 4 hours may be booked in business class without approval"
    answer = lab.CitedAnswer(
        claims=[
            lab.Claim("Policy text.", [lab.Citation("travel-001", "Economy class is the default for every employee.")]),
            lab.Claim("Two cites.", [lab.Citation("faq-020", q1), lab.Citation("faq-020", q1)]),
        ]
    )
    assert lab.verify_answer(answer, passages, archived=ARCHIVED).stale == [1]


def test_current_sources_are_not_stale(passages):
    report = lab.verify_answer(lab.parse_claude_response(fixture("claude_ok.json")), passages, archived=ARCHIVED)
    assert report.stale == [] and report.ok and report.cited_claims == 2


def test_without_archived_nothing_is_stale(passages):
    answer = lab.parse_marked_answer(fixture("marked_answer.txt"))
    assert lab.verify_answer(answer, passages).stale == []
    assert lab.verify_answer(answer, passages, archived=None).stale == []


def test_unknown_passage_is_not_reported_as_stale(passages):
    answer = lab.CitedAnswer(claims=[lab.Claim("Made up.", [lab.Citation("faq-999", "anything")])])
    report = lab.verify_answer(answer, passages, archived={"faq-999"})
    assert report.stale == [], "only passages you actually sent can be stale"
    assert [p.kind for p in report.problems] == ["unknown passage"]
