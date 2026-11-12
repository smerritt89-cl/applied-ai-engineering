"""Tests for lab 04 (Studio 5). All offline: they score recorded, synthetic predictions.

Run:  pytest studio-5/04-benchmark -q
"""
from __future__ import annotations

import copy
import json
import pathlib
import random
import re

import pytest

import starter as lab

FIX = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def cases():
    return lab.load_test_set(FIX / "test_set.jsonl")


@pytest.fixture(scope="module")
def runs():
    return {name: lab.load_run(FIX / f"{name}.json") for name in ("ft-lora", "base", "frontier")}


@pytest.fixture(scope="module")
def costs():
    return json.loads((FIX / "costs.json").read_text())


GOLD = {"is_action_item": True, "owner": "Priya", "due_date": "2026-11-13", "priority": "high"}


# ---------------------------------------------------------------- field scoring


def test_normalize_strings_only():
    assert lab.normalize("  Priya ") == "priya"
    assert lab.normalize("PRIYA") == lab.normalize("priya")
    assert lab.normalize(None) is None
    assert lab.normalize(True) is True


def test_field_correct_basics():
    assert lab.field_correct(dict(GOLD), GOLD, "owner")
    assert lab.field_correct({**GOLD, "owner": "priya "}, GOLD, "owner"), "case and surrounding whitespace are formatting, not errors"
    assert not lab.field_correct({**GOLD, "owner": "Sam"}, GOLD, "owner")
    assert not lab.field_correct({**GOLD, "due_date": "2026-11-14"}, GOLD, "due_date"), "dates must match exactly"


def test_field_correct_missing_and_null():
    assert not lab.field_correct(None, GOLD, "owner"), "an unparseable output is wrong, not skipped"
    partial = {k: v for k, v in GOLD.items() if k != "priority"}
    assert not lab.field_correct(partial, GOLD, "priority"), "a missing key is wrong"
    gold_null = {**GOLD, "due_date": None}
    assert lab.field_correct({**GOLD, "due_date": None}, gold_null, "due_date"), "null matches null"
    assert not lab.field_correct({**GOLD, "due_date": "2026-11-13"}, gold_null, "due_date"), "an invented date is wrong"


# ---------------------------------------------------------------- run scoring and integrity checks


def test_score_run_keeps_failures_in_the_denominator(cases, runs):
    scored = lab.score_run(cases, runs["ft-lora"])
    assert len(scored) == len(cases) == 150
    assert [s["id"] for s in scored] == [c["id"] for c in cases], "keep test-set order"
    unparsed = [s for s in scored if not s["parsed"]]
    assert len(unparsed) == 4
    assert all(s["exact"] == 0 and sum(s["fields"].values()) == 0 for s in unparsed)


def test_score_run_refuses_a_different_test_set(cases):
    stale = lab.load_run(FIX / "ft-lora-stale.json")
    with pytest.raises(ValueError, match="(?i)test set|fingerprint"):
        lab.score_run(cases, stale)


def test_score_run_refuses_edited_gold_labels(cases, runs):
    edited = copy.deepcopy(cases)
    edited[0]["gold"]["priority"] = "low"  # someone "fixed" a label after the runs were recorded
    with pytest.raises(ValueError):
        lab.score_run(edited, runs["ft-lora"])


def test_score_run_refuses_duplicates_and_missing_ids(cases, runs):
    dup = copy.deepcopy(runs["frontier"])
    dup["predictions"][1] = dict(dup["predictions"][0])
    with pytest.raises(ValueError, match="(?i)duplicate"):
        lab.score_run(cases, dup)
    short = copy.deepcopy(runs["frontier"])
    short["predictions"] = short["predictions"][:-5]  # the slow tail was dropped
    with pytest.raises(ValueError):
        lab.score_run(cases, short)


def test_aggregate_metrics_on_a_tiny_example():
    scored = [
        {"id": "a", "parsed": True, "fields": {"is_action_item": 1, "owner": 1, "due_date": 1, "priority": 1}, "exact": 1},
        {"id": "b", "parsed": True, "fields": {"is_action_item": 1, "owner": 0, "due_date": 1, "priority": 1}, "exact": 0},
        {"id": "c", "parsed": False, "fields": {"is_action_item": 0, "owner": 0, "due_date": 0, "priority": 0}, "exact": 0},
        {"id": "d", "parsed": True, "fields": {"is_action_item": 1, "owner": 1, "due_date": 0, "priority": 1}, "exact": 0},
    ]
    assert lab.field_accuracy(scored) == {"is_action_item": 0.75, "owner": 0.5, "due_date": 0.5, "priority": 0.75}
    assert lab.exact_match(scored) == 0.25
    assert lab.parse_rate(scored) == 0.75


def test_fixture_headline_numbers(cases, runs):
    ft = lab.score_run(cases, runs["ft-lora"])
    fr = lab.score_run(cases, runs["frontier"])
    base = lab.score_run(cases, runs["base"])
    assert round(lab.exact_match(ft), 4) == round(122 / 150, 4)
    assert round(lab.exact_match(fr), 4) == round(111 / 150, 4)
    assert round(lab.exact_match(base), 4) == round(64 / 150, 4)
    assert lab.field_accuracy(fr)["owner"] > lab.field_accuracy(ft)["owner"], "the frontier model is better on owners"
    assert lab.field_accuracy(ft)["priority"] > lab.field_accuracy(fr)["priority"], "the adapter learned the house priority convention"


# ---------------------------------------------------------------- intervals


def _reference_bootstrap(values, n_boot, alpha, seed):
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return means[int(alpha / 2 * n_boot)], means[int((1 - alpha / 2) * n_boot) - 1]


def test_bootstrap_follows_the_docstring_procedure():
    values = [1] * 70 + [0] * 30
    got = lab.bootstrap_ci(values, n_boot=500, alpha=0.05, seed=7)
    assert got == _reference_bootstrap(values, 500, 0.05, 7), "use random.Random(seed), randrange, and the stated percentile positions"
    assert got == lab.bootstrap_ci(values, n_boot=500, alpha=0.05, seed=7), "same seed, same interval"


def test_bootstrap_sanity():
    values = [1] * 70 + [0] * 30
    lo, hi = lab.bootstrap_ci(values)
    assert lo < 0.7 < hi
    assert 0.08 < hi - lo < 0.25, "about plus or minus 9 points for n = 100 at 70 percent"
    assert lab.bootstrap_ci([1] * 40) == (1.0, 1.0)
    lo_big, hi_big = lab.bootstrap_ci([1] * 700 + [0] * 300, n_boot=500)
    assert hi_big - lo_big < hi - lo, "ten times the data gives a narrower interval"


def test_paired_difference(cases, runs):
    ft = [s["exact"] for s in lab.score_run(cases, runs["ft-lora"])]
    fr = [s["exact"] for s in lab.score_run(cases, runs["frontier"])]
    same = lab.paired_bootstrap_diff(fr, fr)
    assert same == {"diff": 0.0, "lower": 0.0, "upper": 0.0}
    res = lab.paired_bootstrap_diff(ft, fr)
    assert set(res) == {"diff", "lower", "upper"}
    assert round(res["diff"], 4) == round(11 / 150, 4)
    assert res["lower"] <= res["diff"] <= res["upper"]
    d = [a - b for a, b in zip(ft, fr)]
    assert (res["lower"], res["upper"]) == _reference_bootstrap(d, 2000, 0.05, 0), "resample the same indices for both systems"
    with pytest.raises(ValueError):
        lab.paired_bootstrap_diff(ft, fr[:-1])


def test_pairing_narrows_the_interval(cases, runs):
    """Pairing removes the shared difficulty of each case, so the paired interval is narrower
    than one from resampling the two systems independently."""
    ft = [s["exact"] for s in lab.score_run(cases, runs["ft-lora"])]
    fr = [s["exact"] for s in lab.score_run(cases, runs["frontier"])]
    paired = lab.paired_bootstrap_diff(ft, fr)
    rng = random.Random(1)
    n = len(ft)
    diffs = sorted(
        sum(ft[rng.randrange(n)] for _ in range(n)) / n - sum(fr[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(2000)
    )
    unpaired_width = diffs[1949] - diffs[50]
    assert paired["upper"] - paired["lower"] < unpaired_width


# ---------------------------------------------------------------- cost and latency


def test_api_cost_per_1000():
    run = {"predictions": [
        {"input_tokens": 600, "output_tokens": 80},
        {"input_tokens": 400, "output_tokens": 120},
    ]}
    # mean task: 500 in, 100 out -> 500 * 2 / 1e6 + 100 * 10 / 1e6 = 0.002 dollars -> $2.00 per 1,000
    assert lab.api_cost_per_1000(run, 2.0, 10.0) == pytest.approx(2.0)


def test_selfhost_cost_depends_on_utilization():
    full = lab.selfhost_cost_per_1000(0.80, 3000, 1.0)
    assert full == pytest.approx(0.2667, abs=1e-4)
    assert lab.selfhost_cost_per_1000(0.80, 3000, 0.2) == pytest.approx(5 * full), "idle GPU hours still cost money"
    for bad in (0, -1):
        with pytest.raises(ValueError):
            lab.selfhost_cost_per_1000(0.80, bad, 1.0)
    for bad in (0, 1.5):
        with pytest.raises(ValueError):
            lab.selfhost_cost_per_1000(0.80, 3000, bad)


def test_cost_dispatch(runs, costs):
    assert lab.cost_per_1000(runs["ft-lora"], costs["ft-lora"]) == pytest.approx(1.3333, abs=1e-3)
    frontier = lab.cost_per_1000(runs["frontier"], costs["frontier"])
    assert 1.8 < frontier < 2.1
    with pytest.raises(ValueError):
        lab.cost_per_1000(runs["frontier"], {"kind": "vibes"})


def test_latency_summary():
    run = {"predictions": [{"latency_s": x} for x in (0.2, 0.4, 0.3, 5.0, 0.5, 0.35, 0.45, 0.25, 0.3, 0.4)]}
    assert lab.latency_summary(run) == {"p50": 0.35, "p95": 5.0}


# ---------------------------------------------------------------- report


def test_report(cases, runs, costs):
    summary = lab.summarize(cases, list(runs.values()), costs, reference="frontier")
    md = lab.render_report(summary)
    assert md.startswith("# Benchmark")
    assert summary["test_set_sha256"][:12] in md
    for name in ("ft-lora", "base", "frontier"):
        assert re.search(rf"^\| {re.escape(name)} \|", md, re.M), f"one table row for {name}"
    assert re.search(r"81\.3% \[\d+\.\d, \d+\.\d\]", md), "exact match with its interval for ft-lora"
    assert "$1.33" in md, "self-hosted cost per 1,000 for ft-lora"
    assert re.search(r"^- ft-lora vs frontier: \+7\.3 points \[[+-]\d+\.\d, \+\d+\.\d\]", md, re.M)
    assert re.search(r"^- base vs frontier: -\d+\.\d points", md, re.M)
    assert "frontier vs frontier" not in md
    assert re.search(r"(?i)sampling of test cases", md), "say what the intervals do not cover"


def test_cli_writes_report(tmp_path):
    out = tmp_path / "report.md"
    code = lab.main([
        str(FIX / "test_set.jsonl"), str(FIX / "ft-lora.json"), str(FIX / "frontier.json"),
        "--costs", str(FIX / "costs.json"), "--reference", "frontier", "--out", str(out),
    ])
    assert code == 0
    assert out.read_text().startswith("# Benchmark")
