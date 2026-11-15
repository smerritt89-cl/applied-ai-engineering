"""Acceptance tests for CHANGE.md (lab 05): resolve_date supports 'in N business days'.
Offline only; no API key needed."""
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

pytestmark = pytest.mark.change

MEETING = "2026-11-11"  # a Wednesday


@pytest.mark.parametrize(
    "phrase,meeting,expected",
    [
        ("in 1 business day", MEETING, "2026-11-12"),       # Wed -> Thu
        ("in 2 business days", MEETING, "2026-11-13"),      # Wed -> Fri
        ("in 3 business days", MEETING, "2026-11-16"),      # skips Sat and Sun
        ("in 5 business days", MEETING, "2026-11-18"),      # one working week
        ("in 10 business days", MEETING, "2026-11-25"),
        ("in 1 business day", "2026-11-13", "2026-11-16"),  # Fri -> Mon
        ("in 1 business day", "2026-11-14", "2026-11-16"),  # Sat -> Mon
        ("  In 3   BUSINESS days ", MEETING, "2026-11-16"),  # same normalization as other phrases
    ],
)
def test_business_days(phrase, meeting, expected):
    assert resolve_date(phrase, meeting) == expected


def test_calendar_days_unchanged():
    assert resolve_date("in 3 days", MEETING) == "2026-11-14"
    assert resolve_date("in 1 week", MEETING) == "2026-11-18"


def test_tool_description_mentions_business_days():
    (tool,) = [t for t in TOOLS if t["name"] == "resolve_date"]
    assert "business days" in tool["description"], "the model only uses phrases the description promises"


def test_error_message_lists_business_days():
    with pytest.raises(ToolError) as err:
        resolve_date("end of quarter", MEETING)
    assert "business days" in str(err.value)


def test_business_days_through_the_dispatcher(tmp_path):
    content, is_error = run_tool("resolve_date", {"phrase": "in 3 business days", "meeting_date": MEETING},
                                 team=load_team(), tasks_path=tmp_path / "tasks.json")
    assert not is_error
    assert json.loads(content) == {"date": "2026-11-16"}
