"""Tests for lab 02. Offline tests use fake candidates; the live test calls Claude.

Run: pytest studio-1/02-model-bakeoff -q
"""
from __future__ import annotations

import csv
import os

import pytest

# Every lab has a module named `starter`, so make sure this file imports ITS OWN copy
# even when pytest collects several labs in one run.
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).parent))
for _mod in ("starter", "solution"):
    _sys.modules.pop(_mod, None)

from starter import (
    CSV_COLUMNS,
    PRICES,
    Candidate,
    Result,
    auto_score,
    available_candidates,
    cost_usd,
    load_prompts,
    load_scores_from_csv,
    percentile,
    pick_winner,
    run_bakeoff,
    run_one,
    summarize,
    write_csv,
)


class StepClock:
    """Each call returns a time `step` seconds after the previous one."""

    def __init__(self, step: float = 1.5):
        self.t, self.step = 0.0, step

    def __call__(self):
        now = self.t
        self.t += self.step
        return now


def fake(model: str, text: str = "ok", tin: int = 1000, tout: int = 200, fail: bool = False) -> Candidate:
    def call(prompt, max_tokens):
        if fail:
            raise TimeoutError("simulated timeout")
        return text, tin, tout, "end_turn"

    return Candidate("fake", model, call)


PROMPTS = [{"id": "p1", "prompt": "a"}, {"id": "p2", "prompt": "b"}]


# --------------------------------------------------------------------------- pricing


def test_cost_usd():
    assert cost_usd("claude-haiku-5-5", 1000, 200) == pytest.approx((1000 * 0.10 + 200 * 0.50) / 1e6)
    assert cost_usd("claude-sonnet-5-5", 1_000_000, 1_000_000) == pytest.approx(12.0)
    with pytest.raises(KeyError):
        cost_usd("mystery-model", 1, 1)


def test_price_table_is_sane():
    for model, p in PRICES.items():
        assert p["output"] >= p["input"] > 0, f"{model}: output should not be cheaper than input"


# --------------------------------------------------------------------------- running


def test_run_one_success_records_everything():
    r = run_one(fake("claude-haiku-5-5", "hello"), {"id": "p1", "prompt": "x"}, clock=StepClock(1.5))
    assert isinstance(r, Result)
    assert (r.prompt_id, r.model, r.output, r.stop_reason) == ("p1", "claude-haiku-5-5", "hello", "end_turn")
    assert (r.input_tokens, r.output_tokens) == (1000, 200)
    assert r.latency_s == pytest.approx(1.5)
    assert r.cost_usd == pytest.approx(cost_usd("claude-haiku-5-5", 1000, 200))
    assert r.error == ""


def test_run_one_captures_failures_instead_of_crashing():
    r = run_one(fake("claude-haiku-5-5", fail=True), {"id": "p1", "prompt": "x"}, clock=StepClock(2.0))
    assert r.error.startswith("TimeoutError"), "error should name the exception type"
    assert "simulated timeout" in r.error
    assert r.cost_usd == 0 and r.output == ""
    assert r.latency_s == pytest.approx(2.0), "failures have latency too"


def test_run_bakeoff_runs_every_pair_in_prompt_major_order():
    cands = [fake("claude-haiku-5-5"), fake("claude-sonnet-5-5")]
    rs = run_bakeoff(cands, PROMPTS, clock=StepClock())
    assert [(r.prompt_id, r.model) for r in rs] == [
        ("p1", "claude-haiku-5-5"), ("p1", "claude-sonnet-5-5"),
        ("p2", "claude-haiku-5-5"), ("p2", "claude-sonnet-5-5"),
    ]


# --------------------------------------------------------------------------- scoring and aggregation


def test_auto_score():
    r = Result("p1", "x", "m", output="Total 48 features, mean 12.")
    assert auto_score(r, ["48", "12"]) == 1.0
    assert auto_score(r, ["48", "fifty"]) == 0.5
    assert auto_score(Result("p1", "x", "m", output="GROUP by"), ["group BY"]) == 1.0, "case-insensitive"
    assert auto_score(Result("p1", "x", "m", output="48", error="Boom"), ["48"]) == 0.0, "errors score 0"
    assert auto_score(r, []) == 1.0


def test_percentile_nearest_rank():
    assert percentile([], 95) is None
    assert percentile([3.0], 95) == 3.0
    vals = [float(v) for v in range(1, 21)]  # 1..20
    assert percentile(vals, 50) == 10.0
    assert percentile(vals, 95) == 19.0
    assert percentile(vals, 100) == 20.0
    assert percentile([5.0, 1.0, 3.0], 0) == 1.0, "sort first; rank is at least 1"


def _results():
    rs = []
    for i in range(10):
        rs.append(Result(f"p{i}", "anthropic", "big", output="x", input_tokens=1000, output_tokens=500,
                         latency_s=2.0 + i, cost_usd=0.012))
        rs.append(Result(f"p{i}", "anthropic", "small", output="x", input_tokens=1000, output_tokens=300,
                         latency_s=1.0, cost_usd=0.001))
    rs.append(Result("p10", "google", "flaky", error="TimeoutError: x", latency_s=30.0))
    rs.append(Result("p11", "google", "flaky", output="x", output_tokens=100, latency_s=1.0, cost_usd=0.002))
    return rs


def _scores(rs):
    s = {}
    for r in rs:
        s[(r.prompt_id, r.model)] = {"big": 0.95, "small": 0.85, "flaky": 1.0}[r.model]
    s[("p10", "flaky")] = 0.0
    return s


def test_summarize_stats():
    rs = _results()
    summary = summarize(rs, _scores(rs))
    big, small, flaky = summary["big"], summary["small"], summary["flaky"]
    assert big["n"] == 10 and big["errors"] == 0 and big["provider"] == "anthropic"
    assert big["mean_score"] == pytest.approx(0.95)
    assert big["total_cost_usd"] == pytest.approx(0.12)
    assert big["cost_per_task_usd"] == pytest.approx(0.012)
    assert big["p50_latency_s"] == pytest.approx(6.0)
    assert big["p95_latency_s"] == pytest.approx(11.0)
    assert big["mean_output_tokens"] == pytest.approx(500)
    assert small["mean_output_tokens"] == pytest.approx(300)
    assert flaky["errors"] == 1
    assert flaky["mean_score"] == pytest.approx(0.5), "errors count as 0 in the mean"
    assert flaky["p95_latency_s"] == pytest.approx(1.0), "latency stats use successful calls only"


def test_summarize_missing_score_counts_as_zero():
    rs = [Result("p1", "x", "m", output="a", cost_usd=0.0)]
    assert summarize(rs, {})["m"]["mean_score"] == 0.0


def test_pick_winner_prefers_cheapest_passing_model():
    rs = _results()
    summary = summarize(rs, _scores(rs))
    assert pick_winner(summary, 0.8) == "small", "small passes the bar and costs far less"
    assert pick_winner(summary, 0.9) == "big"
    assert pick_winner(summary, 0.99) is None, "flaky has errors, so it never wins"


def test_pick_winner_breaks_cost_ties_on_latency():
    summary = {
        "a": {"mean_score": 0.9, "errors": 0, "cost_per_task_usd": 0.01, "p95_latency_s": 4.0},
        "b": {"mean_score": 0.9, "errors": 0, "cost_per_task_usd": 0.01, "p95_latency_s": 2.0},
    }
    assert pick_winner(summary, 0.8) == "b"


# --------------------------------------------------------------------------- CSV


def test_write_csv_round_trip(tmp_path):
    rs = [
        Result("p2", "anthropic", "small", output="line one\nline, two", input_tokens=10, output_tokens=5,
               latency_s=1.23456, cost_usd=0.0000123, stop_reason="end_turn"),
        Result("p1", "anthropic", "small", error="TimeoutError: x", latency_s=30.0),
    ]
    scores = {("p2", "small"): 0.6666, ("p1", "small"): 0.0}
    path = tmp_path / "out.csv"
    write_csv(rs, scores, path)
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == CSV_COLUMNS
    assert [r["prompt_id"] for r in rows] == ["p1", "p2"], "sorted by prompt_id then model"
    assert rows[1]["output"] == "line one\nline, two", "use the csv module so commas and newlines survive"
    assert rows[1]["auto_score"] == "0.667"
    assert rows[1]["human_score"] == ""
    assert rows[1]["latency_s"] == "1.235"
    assert rows[1]["cost_usd"] == "0.000012"
    assert rows[0]["error"] == "TimeoutError: x"

    # Fill in a human score and re-load: human scores win over auto scores.
    rows[1]["human_score"] = "1.0"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    _, loaded = load_scores_from_csv(path)
    assert loaded[("p2", "small")] == 1.0 and loaded[("p1", "small")] == 0.0


# --------------------------------------------------------------------------- setup


def test_prompts_file_is_well_formed():
    prompts = load_prompts()
    assert len(prompts) >= 5
    ids = [p["id"] for p in prompts]
    assert len(ids) == len(set(ids)), "prompt ids must be unique"
    for p in prompts:
        assert p["prompt"].strip() and isinstance(p.get("must_include", []), list)


def test_missing_keys_are_skipped_not_errors():
    assert available_candidates(env={}) == []


@pytest.mark.live
def test_live_two_claude_tiers_on_one_prompt():
    cands = available_candidates(env=dict(os.environ))
    claude = [c for c in cands if c.provider == "anthropic"]
    assert len(claude) >= 2
    rs = run_bakeoff(claude, load_prompts()[:1], max_tokens=2048)
    assert all(not r.error for r in rs), [r.error for r in rs]
    assert all(r.output_tokens > 0 and r.cost_usd > 0 for r in rs)
