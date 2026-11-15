"""Acceptance tests for CHANGE.md (Studio 4, lab 02): a tool-error budget.

Run on its own:  pytest studio-4/02-research-agent/test_change.py -q
Offline only: a fake client replays scripted responses, so no API key is needed."""
import copy
from types import SimpleNamespace

import pytest

from starter import (
    Budget,
    Tracer,
    load_corpus,
    run_agent,
)

pytestmark = pytest.mark.change


# ---------------------------------------------------------------------------
# The same kind of fake client the main tests use
# ---------------------------------------------------------------------------

def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def reply(stop_reason, *blocks, input_tokens=100, output_tokens=50):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks),
                           usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens))


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        if not self._responses:
            raise AssertionError("the loop made more model calls than the script expected")
        return self._responses.pop(0)


def read(id_, doc_id, start=1, n=40):
    return tool_use(id_, "read_doc", {"doc_id": doc_id, "start_line": start, "max_lines": n})


def search(id_, query, n=5):
    return tool_use(id_, "search_docs", {"query": query, "max_results": n})


@pytest.fixture(scope="module")
def corpus():
    return load_corpus()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_budget_has_a_tool_error_limit_with_default_5():
    assert Budget().max_tool_errors == 5
    assert Budget(max_tool_errors=2).max_tool_errors == 2


def test_run_stops_when_tool_errors_reach_the_limit(corpus):
    # Different bad ids each time, so the repeated-call check never fires.
    client = FakeClient([reply("tool_use", text(f"Trying id {i}."), read(f"t{i}", f"risk-log-{i}"))
                         for i in range(1, 6)])
    tr = Tracer()
    result = run_agent(client, "q", corpus, budget=Budget(max_steps=10, max_tool_errors=3), tracer=tr)
    assert result.status == "budget:tool_errors" and result.partial
    assert result.steps == 3 and len(client.requests) == 3, "stop right after the third failed call"
    assert result.tool_errors == 3
    assert result.answer == "Trying id 3.", "return the latest text as a partial answer"
    last = result.messages[-1]
    assert last["role"] == "user" and last["content"][0]["type"] == "tool_result", \
        "the failing tool_use still gets its tool_result before the run stops"
    stop = tr.events[-1]
    assert stop["kind"] == "stop" and stop["status"] == "budget:tool_errors" and stop["tool_errors"] == 3


def test_errors_in_one_batch_all_count_and_all_get_results(corpus):
    client = FakeClient([reply("tool_use", read("t1", "nope-a"), read("t2", "nope-b"))])
    result = run_agent(client, "q", corpus, budget=Budget(max_tool_errors=2))
    assert result.status == "budget:tool_errors" and result.steps == 1
    ids = [b["tool_use_id"] for b in result.messages[-1]["content"] if b["type"] == "tool_result"]
    assert ids == ["t1", "t2"]


def test_successful_calls_do_not_count(corpus):
    client = FakeClient([
        reply("tool_use", search("t1", "Quillmark renewal")),
        reply("end_turn", text("Done.")),
    ])
    tr = Tracer()
    result = run_agent(client, "q", corpus, budget=Budget(max_tool_errors=1), tracer=tr)
    assert result.status == "done" and result.tool_errors == 0
    assert tr.events[-1]["tool_errors"] == 0


def test_tool_call_budget_placeholder_is_not_a_tool_error(corpus):
    # The second call is refused by the tool-call budget. That is the harness's limit,
    # not a failing tool, so it must not trip the tool-error budget.
    client = FakeClient([
        reply("tool_use", search("t1", "Quillmark"), search("t2", "SSO")),
        reply("end_turn", text("Partial.")),
    ])
    result = run_agent(client, "q", corpus, budget=Budget(max_tool_calls=1, max_tool_errors=1))
    assert result.status == "done" and result.tool_errors == 0
