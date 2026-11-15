"""Acceptance tests for CHANGE.md: list the slowest traces on the dashboard.

Run on their own, once you've made the change in work.py:
    pytest studio-6/03-tracing/test_change.py -q
"""
from __future__ import annotations

import pathlib

import pytest

import starter as lab

HERE = pathlib.Path(__file__).parent

pytestmark = pytest.mark.change


def rec(trace, step, model, latency, cost, status="ok", tin=10, tout=5):
    return {"trace_id": trace, "step": step, "model": model, "latency_ms": latency, "cost_usd": cost,
            "status": status, "input_tokens": tin, "output_tokens": tout, "cache_read_tokens": 0,
            "cache_write_tokens": 0}


SMALL = [
    rec("t1", "triage", "h", 100, 0.001), rec("t1", "reply", "o", 2000, 0.010),
    rec("t2", "triage", "h", 300, 0.001), rec("t2", "reply", "o", 30000, 0.0, status="error", tin=0, tout=0),
    rec("t3", "triage", "h", 200, 0.001, status="refused", tout=0),
    rec("t4", "triage", "h", 150, 0.001), rec("t4", "reply", "o", 1500, 0.010),
]


def test_aggregate_lists_the_three_slowest_traces_by_total_latency():
    agg = lab.aggregate(SMALL)
    assert agg["slowest_traces"] == [
        {"trace_id": "t2", "latency_ms": 30300},
        {"trace_id": "t1", "latency_ms": 2100},
        {"trace_id": "t4", "latency_ms": 1650},
    ], "per-trace latency is the sum of its steps, slowest first, at most three"


def test_ties_are_broken_by_trace_id_and_short_logs_list_fewer():
    agg = lab.aggregate([rec("tb", "triage", "h", 500, 0.0), rec("ta", "triage", "h", 500, 0.0)])
    assert agg["slowest_traces"] == [{"trace_id": "ta", "latency_ms": 500}, {"trace_id": "tb", "latency_ms": 500}]
    assert lab.aggregate([])["slowest_traces"] == []


def test_existing_aggregate_keys_are_unchanged():
    agg = lab.aggregate(SMALL)
    assert set(agg) == {"rows", "traces", "total_cost_usd", "cost_per_trace_usd", "trace_p50_ms",
                        "trace_p95_ms", "failed_traces", "slowest_traces"}
    assert agg["traces"] == 4 and agg["failed_traces"] == 2 and agg["trace_p95_ms"] == 30300


def test_dashboard_shows_the_slowest_traces_after_the_table():
    md = lab.render_markdown(lab.aggregate(SMALL))
    assert "Slowest traces:\n- t2: 30,300 ms\n- t1: 2,100 ms\n- t4: 1,650 ms\n" in md
    assert md.index("| Step | Model |") < md.index("Slowest traces:") < md.index("Percentiles are nearest-rank.")


def test_sample_log_dashboard_links_to_real_trace_ids():
    records = lab.read_jsonl(HERE / "samples" / "sample_log.jsonl")
    agg = lab.aggregate(records)
    ids = {r["trace_id"] for r in records}
    assert len(agg["slowest_traces"]) == 3
    assert all(t["trace_id"] in ids for t in agg["slowest_traces"])
    latencies = [t["latency_ms"] for t in agg["slowest_traces"]]
    assert latencies == sorted(latencies, reverse=True)
    assert latencies[0] >= agg["trace_p95_ms"]
