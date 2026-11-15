"""Acceptance tests for this lab's CHANGE.md task: compare_per_query gains a min_delta parameter.

Run:  pytest studio-2/01-embedding-bakeoff/test_change.py -q
These fail until the change is made in work.py (they are skipped in a normal full run).
"""
from __future__ import annotations

import pytest

import starter as lab

pytestmark = pytest.mark.change


def _report(name, rrs):
    rep = lab.Report(name=name, ks=(1,))
    for qid, rr in rrs.items():
        rep.results.append(lab.QueryResult(qid, qid, ["d"], ["d"], {1: 1.0 if rr == 1 else 0.0}, rr))
    return rep


A = {"q1": 1.0, "q2": 0.25, "q3": 1 / 3, "q4": 0.0}
B = {"q1": 0.5, "q2": 0.2, "q3": 0.5, "q4": 0.0}


def test_small_differences_become_ties():
    out = lab.compare_per_query(_report("a", A), _report("b", B), min_delta=0.1)
    # q1: a ahead by 0.5 (win). q2: a ahead by 0.05 (tie). q3: b ahead by 0.167 (win). q4: equal (tie).
    assert out == {"a_wins": ["q1"], "b_wins": ["q3"], "ties": ["q2", "q4"]}


def test_a_gap_exactly_equal_to_min_delta_is_a_tie():
    a = _report("a", {"q1": 0.5})
    b = _report("b", {"q1": 0.25})
    assert lab.compare_per_query(a, b, min_delta=0.25) == {"a_wins": [], "b_wins": [], "ties": ["q1"]}
    assert lab.compare_per_query(b, a, min_delta=0.25) == {"a_wins": [], "b_wins": [], "ties": ["q1"]}


def test_default_behavior_is_unchanged():
    a, b = _report("a", A), _report("b", B)
    expected = {"a_wins": ["q1", "q2"], "b_wins": ["q3"], "ties": ["q4"]}
    assert lab.compare_per_query(a, b) == expected
    assert lab.compare_per_query(a, b, min_delta=0.0) == expected


def test_negative_min_delta_is_rejected():
    with pytest.raises(ValueError):
        lab.compare_per_query(_report("a", A), _report("b", B), min_delta=-0.1)


def test_mismatched_queries_still_rejected():
    with pytest.raises(ValueError):
        lab.compare_per_query(_report("a", {"q1": 1.0}), _report("b", {"q2": 1.0}), min_delta=0.1)
