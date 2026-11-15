"""Acceptance tests for CHANGE.md: report how much of each arm's cost is output.

Run on their own, once you've made the change in work.py:
    pytest studio-6/02-cost-latency/test_change.py -q
"""
from __future__ import annotations

import pytest

import starter as lab

pytestmark = pytest.mark.change


def _arm(name):
    return [r for r in lab.load_fixture("comparison.json") if r["arm"] == name]


def _expected_share(records):
    """Computed independently: output tokens times the output price, over the whole cost."""
    out = sum(r["usage"]["output_tokens"] * lab.PRICES[r["model"]]["output"] for r in records) / 1_000_000
    total = sum(lab.request_cost(r["usage"], r["model"]) for r in records)
    return out / total


def test_summarize_reports_output_cost_share():
    for arm in ("baseline", "cached"):
        records = _arm(arm)
        share = lab.summarize(records)["output_cost_share"]
        assert share == pytest.approx(_expected_share(records), rel=1e-9)


def test_output_dominates_once_the_prefix_is_cached():
    base = lab.summarize(_arm("baseline"))["output_cost_share"]
    cached = lab.summarize(_arm("cached"))["output_cost_share"]
    assert 0 < base < cached < 1
    assert cached > 0.5, "after caching, output is most of what is left of the bill"


def test_zero_cost_arm_reports_zero_share_instead_of_dividing_by_zero():
    free = [{"model": lab.MODEL, "ttft_s": 0.1, "first_text_s": 0.2, "total_s": 0.3,
             "usage": {"input_tokens": 0, "output_tokens": 0}}]
    assert lab.summarize(free)["output_cost_share"] == 0.0


def test_existing_summary_keys_are_unchanged():
    s = lab.summarize(_arm("cached"))
    assert set(s) == {"n", "total_cost", "mean_cost", "cache_read_fraction", "output_cost_share",
                      "ttft_s", "first_text_s", "total_s"}
    assert s["mean_cost"] == pytest.approx(0.00023025, rel=1e-5)


def test_report_shows_the_share_per_arm():
    report = lab.format_report(lab.compare(lab.load_fixture("comparison.json")))
    assert "output 35% of cost" in report
    assert "output 64% of cost" in report
