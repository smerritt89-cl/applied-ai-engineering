"""Tests for lab 05. Offline tests use a fake client that replays scripted
responses, so they need no API key. Live tests are marked @pytest.mark.live."""
import copy
import json
import os
from types import SimpleNamespace

import pytest

from starter import (
    TOOLS,
    ToolError,
    load_team,
    lookup_teammate,
    resolve_date,
    run_tool,
    run_tool_loop,
)

MEETING = "2026-11-11"  # a Wednesday


# ---------------------------------------------------------------------------
# A fake Anthropic client
# ---------------------------------------------------------------------------

def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def reply(stop_reason, *blocks):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks))


class FakeClient:
    """Replays scripted responses and records every request it receives."""

    def __init__(self, responses, repeat_last=False):
        self._responses = list(responses)
        self._repeat_last = repeat_last
        self.requests = []
        self.messages = self  # so client.messages.create(...) works

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        if not self._responses:
            raise AssertionError("the loop made more API calls than the script expected")
        if self._repeat_last and len(self._responses) == 1:
            return self._responses[0]
        return self._responses.pop(0)


def never_called(name, args):
    raise AssertionError(f"approve() was called for {name}, but it should not have been")


@pytest.fixture
def team():
    return load_team()


@pytest.fixture
def tasks_path(tmp_path):
    return tmp_path / "tasks.json"


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

def test_tool_definitions_are_strict_and_described():
    assert {t["name"] for t in TOOLS} == {"lookup_teammate", "resolve_date", "create_task"}
    for t in TOOLS:
        assert len(t["description"]) > 80, f"{t['name']}: write a description a new hire could use"
        schema = t["input_schema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False, "strict: true needs additionalProperties: false"
        assert set(schema["required"]) == set(schema["properties"]), f"{t['name']}: mark every field required"
        assert t.get("strict") is True


# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------

def test_lookup_teammate_by_alias_and_case(team):
    assert lookup_teammate("priya", team)[0]["email"] == "priya.raman@example.com"
    assert lookup_teammate("Sammy", team)[0]["name"] == "Sam Ortiz"


def test_lookup_teammate_ambiguous_returns_all(team):
    names = {m["name"] for m in lookup_teammate("Marcus", team)}
    assert names == {"Marcus Lee", "Marcus Okafor"}


def test_lookup_teammate_unknown_raises(team):
    with pytest.raises(ToolError):
        lookup_teammate("Jordan", team)


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("today", "2026-11-11"),
        ("tomorrow", "2026-11-12"),
        ("in 3 days", "2026-11-14"),
        ("in 1 week", "2026-11-18"),
        ("in 2 weeks", "2026-11-25"),
        ("Friday", "2026-11-13"),
        ("this Friday", "2026-11-13"),
        ("next Friday", "2026-11-20"),
        ("next Monday", "2026-11-16"),
        ("Wednesday", "2026-11-18"),
        ("  NEXT   friday ", "2026-11-20"),
    ],
)
def test_resolve_date(phrase, expected):
    assert resolve_date(phrase, MEETING) == expected


@pytest.mark.parametrize("phrase,meeting", [("sometime soon", MEETING), ("end of quarter", MEETING),
                                            ("tomorrow", "11/11/2026")])
def test_resolve_date_rejects_what_it_cannot_do(phrase, meeting):
    with pytest.raises(ToolError) as err:
        resolve_date(phrase, meeting)
    assert len(str(err.value)) > 20, "error messages should tell the model what to do instead"


# ---------------------------------------------------------------------------
# Dispatcher and gating
# ---------------------------------------------------------------------------

GOOD_TASK = {
    "title": "Send revised pricing deck to client",
    "owner_email": "priya.raman@example.com",
    "due_date": "2026-11-20",
    "evidence_quote": "I'll send the revised pricing deck to the client by next Friday.",
}


def test_read_tools_never_ask_for_approval(team, tasks_path):
    content, is_error = run_tool("lookup_teammate", {"name": "Dana"}, never_called, team=team, tasks_path=tasks_path)
    assert not is_error and "dana.whitfield@example.com" in content
    content, is_error = run_tool("resolve_date", {"phrase": "next Friday", "meeting_date": MEETING},
                                 never_called, team=team, tasks_path=tasks_path)
    assert not is_error and json.loads(content)["date"] == "2026-11-20"


def test_tool_failures_become_error_results(team, tasks_path):
    for name, args in [("lookup_teammate", {"name": "Jordan"}),
                       ("resolve_date", {"phrase": "whenever", "meeting_date": MEETING}),
                       ("delete_everything", {}),
                       ("resolve_date", {"phrase": "today"})]:  # missing a field
        content, is_error = run_tool(name, args, never_called, team=team, tasks_path=tasks_path)
        assert is_error is True, f"{name} {args} should be an error result, not an exception"
        assert isinstance(content, str) and content


def test_write_tool_declined_writes_nothing(team, tasks_path):
    asked = []
    content, is_error = run_tool("create_task", GOOD_TASK, lambda n, a: asked.append(n) or False,
                                 team=team, tasks_path=tasks_path)
    assert asked == ["create_task"], "the write tool must ask for approval"
    assert is_error is True and "declined" in content.lower()
    assert not tasks_path.exists(), "a declined write must not touch the task file"


def test_write_tool_default_approver_denies(team, tasks_path):
    _, is_error = run_tool("create_task", GOOD_TASK, team=team, tasks_path=tasks_path)
    assert is_error is True and not tasks_path.exists(), "the default must be deny"


def test_write_tool_approved_appends(team, tasks_path):
    for _ in range(2):
        content, is_error = run_tool("create_task", GOOD_TASK, lambda n, a: True, team=team, tasks_path=tasks_path)
        assert not is_error
    saved = json.loads(tasks_path.read_text())
    assert [t["id"] for t in saved] == [1, 2], "create_task appends; it never overwrites"


def test_invalid_write_is_rejected_before_asking_a_human(team, tasks_path):
    bad = dict(GOOD_TASK, owner_email="someone@else.com")
    content, is_error = run_tool("create_task", bad, never_called, team=team, tasks_path=tasks_path)
    assert is_error and "lookup_teammate" in content
    bad = dict(GOOD_TASK, due_date="next Friday")
    _, is_error = run_tool("create_task", bad, never_called, team=team, tasks_path=tasks_path)
    assert is_error and not tasks_path.exists()


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

def test_loop_returns_parallel_results_in_one_user_message(team, tasks_path):
    client = FakeClient([
        reply("tool_use",
              text("Looking up the owner and the date."),
              tool_use("toolu_1", "lookup_teammate", {"name": "Priya"}),
              tool_use("toolu_2", "resolve_date", {"phrase": "next Friday", "meeting_date": MEETING})),
        reply("end_turn", text("Priya owns the deck, due 2026-11-20.")),
    ])
    result = run_tool_loop(client, "notes...", approve=never_called, team=team, tasks_path=tasks_path)

    assert result.status == "done"
    assert result.final_text == "Priya owns the deck, due 2026-11-20."
    assert len(client.requests) == 2

    second = client.requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assistant = second[1]["content"]
    assert any(getattr(b, "type", None) == "tool_use" for b in assistant), "append the full response.content"
    results = second[2]["content"]
    assert isinstance(results, list) and len(results) == 2, "both results go in ONE user message"
    assert [r["type"] for r in results] == ["tool_result", "tool_result"]
    assert [r["tool_use_id"] for r in results] == ["toolu_1", "toolu_2"]
    assert not any(r.get("is_error") for r in results)
    assert json.loads(results[1]["content"])["date"] == "2026-11-20"


def test_loop_sends_tools_and_no_forced_tool_choice(team, tasks_path):
    client = FakeClient([reply("end_turn", text("Nothing to do."))])
    run_tool_loop(client, "hi", team=team, tasks_path=tasks_path)
    req = client.requests[0]
    assert req["tools"] == TOOLS
    assert req.get("tool_choice") in (None, {"type": "auto"}), "forced tool_choice is rejected on Opus 5.5"


def test_loop_marks_errors_with_is_error(team, tasks_path):
    client = FakeClient([
        reply("tool_use", tool_use("toolu_9", "resolve_date", {"phrase": "whenever", "meeting_date": MEETING})),
        reply("end_turn", text("I could not resolve that date.")),
    ])
    result = run_tool_loop(client, "notes", team=team, tasks_path=tasks_path)
    (r,) = client.requests[1]["messages"][2]["content"]
    assert r["is_error"] is True and r["tool_use_id"] == "toolu_9"
    assert result.tool_calls[0][2] is True, "log is_error for each call"


def test_loop_never_writes_without_approval(team, tasks_path):
    client = FakeClient([
        reply("tool_use", tool_use("toolu_w", "create_task", GOOD_TASK)),
        reply("end_turn", text("The task was not created.")),
    ])
    result = run_tool_loop(client, "notes", approve=lambda n, a: False, team=team, tasks_path=tasks_path)
    assert result.status == "done"
    assert not tasks_path.exists()
    (r,) = client.requests[1]["messages"][2]["content"]
    assert r["is_error"] is True


def test_loop_stops_at_max_iterations(team, tasks_path):
    looping = reply("tool_use", tool_use("toolu_x", "lookup_teammate", {"name": "Sam"}))
    client = FakeClient([looping], repeat_last=True)
    result = run_tool_loop(client, "notes", max_iterations=3, team=team, tasks_path=tasks_path)
    assert result.status == "max_iterations"
    assert len(client.requests) == 3, "max_iterations bounds the number of model calls"


def test_loop_does_not_run_tools_after_truncation(team, tasks_path):
    client = FakeClient([reply("max_tokens", tool_use("toolu_t", "create_task", GOOD_TASK))])
    result = run_tool_loop(client, "notes", approve=never_called, team=team, tasks_path=tasks_path)
    assert result.status == "stopped:max_tokens"
    assert not tasks_path.exists()


# ---------------------------------------------------------------------------
# Live tests (cost: a few cents on claude-opus-5-5)
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_live_lookup_and_date(team, tasks_path):
    import anthropic

    notes = ("Meeting date: 2026-11-11.\nPriya: I'll send the revised pricing deck to the client "
             "by next Friday.\nFind the owner's email and the due date. Do not create tasks.")
    result = run_tool_loop(anthropic.Anthropic(), notes, team=team, tasks_path=tasks_path)
    assert result.status == "done", result.status
    names = [c[0] for c in result.tool_calls]
    assert "lookup_teammate" in names and "resolve_date" in names
    assert "priya.raman@example.com" in result.final_text
    assert "2026-11-20" in result.final_text


@pytest.mark.live
def test_live_declined_write_is_not_retried_forever(team, tasks_path):
    import anthropic

    notes = ("Meeting date: 2026-11-11.\nDana: I can have the onboarding mockups ready tomorrow.\n"
             "Create a task for this action item.")
    result = run_tool_loop(anthropic.Anthropic(), notes, approve=lambda n, a: False,
                           team=team, tasks_path=tasks_path)
    assert not tasks_path.exists()
    assert result.status in ("done", "max_iterations")
    writes = [c for c in result.tool_calls if c[0] == "create_task"]
    assert 1 <= len(writes) <= 2, f"expected the model to stop after a decline, saw {len(writes)} attempts"
