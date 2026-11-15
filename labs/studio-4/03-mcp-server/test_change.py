"""Acceptance tests for CHANGE.md (lab 03, Studio 4): a label filter on list_issues.

Offline: no API key, no MCP SDK. Run on its own once the change is made:
    pytest studio-4/03-mcp-server/test_change.py -q
"""
from __future__ import annotations

import copy
import json
import pathlib

import pytest

import starter as lab

pytestmark = pytest.mark.change

DATA = pathlib.Path(__file__).parent / "data" / "issues.json"


@pytest.fixture
def tracker() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def ids(summaries):
    return [i["id"] for i in summaries]


def test_label_filter_returns_matching_issues_in_file_order(tracker):
    assert ids(lab.list_issues(tracker, label="launch-blocker")) == ["HAR-101", "HAR-104", "HAR-107"]


def test_label_combines_with_status(tracker):
    assert ids(lab.list_issues(tracker, status="open", label="launch-blocker")) == ["HAR-107"]
    assert ids(lab.list_issues(tracker, status="blocked", label="launch-blocker")) == ["HAR-104"]


def test_label_combines_with_assignee_and_limit(tracker):
    assert ids(lab.list_issues(tracker, assignee="dana.whitfield", label="process")) == ["HAR-103", "HAR-107"]
    assert ids(lab.list_issues(tracker, label="launch-blocker", limit=2)) == ["HAR-101", "HAR-104"]


def test_label_is_normalized(tracker):
    assert ids(lab.list_issues(tracker, label="  Launch-Blocker ")) == ["HAR-101", "HAR-104", "HAR-107"]


def test_unknown_but_well_formed_label_is_an_empty_list(tracker):
    assert lab.list_issues(tracker, label="kubernetes") == []


@pytest.mark.parametrize("bad", ["", "   ", "launch blocker", "launch_blocker", "x" * 41, 7, ["auth"]])
def test_malformed_label_raises_tracker_error_naming_the_format(tracker, bad):
    with pytest.raises(lab.TrackerError, match="launch-blocker"):
        lab.list_issues(tracker, label=bad)


def test_validate_label_exists_and_normalizes():
    assert lab.validate_label(" Billing ") == "billing"
    with pytest.raises(lab.TrackerError):
        lab.validate_label(None)


def test_existing_calls_still_work(tracker):
    # No label: same results as before, and the old positional order (status, assignee, limit) still works.
    assert ids(lab.list_issues(tracker, status="open")) == ["HAR-102", "HAR-105", "HAR-106", "HAR-107"]
    assert len(lab.list_issues(tracker, None, None, 2)) == 2
    assert set(lab.list_issues(tracker, label="auth")[0]) == {"id", "title", "status", "priority", "assignee"}


def test_label_filter_does_not_modify_the_tracker(tracker):
    before = copy.deepcopy(tracker)
    lab.list_issues(tracker, label="launch-blocker")
    assert tracker == before
