"""Acceptance tests for CHANGE.md (Studio 4 lab 01): flag unowned action items in team updates.

Run:  pytest studio-4/01-workflow-patterns/test_change.py -q
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import starter as lab

pytestmark = pytest.mark.change


def reply(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn")


class FakeClient:
    """Records every messages.create call and returns scripted replies in order."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.replies:
            raise AssertionError(f"unexpected extra model call #{len(self.calls)} to {kwargs.get('model')}")
        return reply(self.replies.pop(0))

    def models_called(self):
        return [c["model"] for c in self.calls]


def fact(kind, text, owner, quote):
    return {"kind": kind, "text": text, "owner": owner, "quote": quote}


FACTS = [
    fact("decision", "Launch moves from Nov 20 to Dec 4", None, "We agreed to move the launch from Nov 20 to Dec 4"),
    fact("action", "Revised checkout mockups", "Dana Whitfield", "Dana will deliver the revised checkout mockups by Wednesday."),
    fact("action", "Update the release checklist", None, "Someone should update the release checklist before the launch."),
    fact("risk", "Payments vendor rate limits unconfirmed", None, "the payments vendor still hasn't confirmed their API rate limits."),
]

PLAIN = "Launch moves to Dec 4. Dana Whitfield delivers the mockups Wednesday."
FLAGGED = PLAIN + "\n\nNeeds an owner:\n- Update the release checklist"


def test_team_draft_without_the_heading_is_a_problem():
    assert "unowned actions not flagged: 1" in lab.code_checks(PLAIN, FACTS, "team")


def test_team_draft_with_the_heading_passes_any_case():
    assert lab.code_checks(FLAGGED, FACTS, "team") == []
    assert lab.code_checks(FLAGGED.replace("Needs an owner", "NEEDS AN OWNER"), FACTS, "team") == []


def test_count_matches_the_number_of_unowned_actions():
    more = FACTS + [fact("action", "Book the launch retro", None, "retro")]
    assert "unowned actions not flagged: 2" in lab.code_checks(PLAIN, more, "team")


def test_other_audiences_are_unchanged():
    assert not any(p.startswith("unowned") for p in lab.code_checks(PLAIN, FACTS, "exec"))
    assert not any(p.startswith("unowned") for p in lab.code_checks(PLAIN, FACTS, "client"))


def test_team_prompt_lists_the_unowned_actions_under_the_heading():
    client = FakeClient([FLAGGED])
    lab.draft_update(client, FACTS, "team")
    prompt = client.calls[0]["messages"][0]["content"]
    assert "Needs an owner" in prompt and "- Update the release checklist" in prompt
    assert "- Revised checkout mockups" not in prompt, "only unowned actions belong in the list"


def test_exec_prompt_has_no_heading_instruction():
    client = FakeClient([PLAIN])
    lab.draft_update(client, FACTS, "exec")
    assert "Needs an owner" not in client.calls[0]["messages"][0]["content"]


def test_refine_sends_the_problem_back_and_skips_the_review():
    client = FakeClient([PLAIN, FLAGGED, json.dumps({"pass": True, "problems": []})])
    result = lab.refine(client, FACTS, "team")
    assert result.approved is True and result.rounds == 2 and result.draft == FLAGGED
    assert result.history[0] == ["unowned actions not flagged: 1"]
    assert client.models_called() == [lab.MODEL, lab.MODEL, lab.EVALUATOR_MODEL]
    assert "unowned actions not flagged: 1" in client.calls[1]["messages"][0]["content"]
