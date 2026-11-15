"""Acceptance tests for CHANGE.md: a p95 latency budget in pick_winner.

Run on their own, once you've made the change in work.py:
    pytest studio-1/02-model-bakeoff/test_change.py -q
"""
from __future__ import annotations

import pytest

# Every lab has a module named `starter`, so make sure this file imports ITS OWN copy
# even when pytest collects several labs in one run.
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).parent))
for _mod in ("starter", "solution"):
    _sys.modules.pop(_mod, None)

from starter import Result, pick_winner, summarize

pytestmark = pytest.mark.change


def _model(cost, p95, score=0.9, errors=0):
    return {"mean_score": score, "errors": errors, "cost_per_task_usd": cost, "p95_latency_s": p95}


SUMMARY = {
    "cheap-slow": _model(0.001, 9.0),
    "mid": _model(0.004, 3.0),
    "pricey-fast": _model(0.010, 1.0),
}


def test_no_budget_keeps_todays_behavior():
    assert pick_winner(SUMMARY, 0.8) == "cheap-slow"
    assert pick_winner(SUMMARY, 0.8, max_p95_s=None) == "cheap-slow"


def test_budget_excludes_models_that_are_too_slow():
    assert pick_winner(SUMMARY, 0.8, max_p95_s=5.0) == "mid", "cheapest model within the budget"
    assert pick_winner(SUMMARY, 0.8, max_p95_s=2.0) == "pricey-fast"


def test_budget_is_inclusive():
    assert pick_winner(SUMMARY, 0.8, max_p95_s=3.0) == "mid", "a p95 exactly at the budget passes"


def test_budget_nobody_meets_returns_none():
    assert pick_winner(SUMMARY, 0.8, max_p95_s=0.5) is None


def test_quality_and_error_rules_still_apply_with_a_budget():
    summary = dict(SUMMARY, **{
        "fast-but-bad": _model(0.0001, 0.2, score=0.5),
        "fast-but-flaky": _model(0.0001, 0.2, errors=1),
    })
    assert pick_winner(summary, 0.8, max_p95_s=2.0) == "pricey-fast"


def test_missing_p95_is_excluded_when_a_budget_is_set():
    summary = {"unmeasured": _model(0.0001, None), "measured": _model(0.01, 1.0)}
    assert pick_winner(summary, 0.8, max_p95_s=2.0) == "measured", "no measured p95 cannot be shown to meet a budget"
    assert pick_winner(summary, 0.8) == "unmeasured", "without a budget, nothing changes"


def test_budget_works_on_a_real_summary():
    rs = []
    for i in range(10):
        rs.append(Result(f"p{i}", "anthropic", "big", output="x", latency_s=1.0, cost_usd=0.012))
        rs.append(Result(f"p{i}", "anthropic", "small", output="x", latency_s=2.0 + i, cost_usd=0.001))
    scores = {(r.prompt_id, r.model): 0.9 for r in rs}
    summary = summarize(rs, scores)
    assert pick_winner(summary, 0.8) == "small"
    assert pick_winner(summary, 0.8, max_p95_s=5.0) == "big", "small's p95 is 11 s, over the budget"


def test_budget_is_keyword_only():
    with pytest.raises(TypeError):
        pick_winner(SUMMARY, 0.8, 5.0)  # a bare third positional number is too easy to misread
