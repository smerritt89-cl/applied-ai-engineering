"""Acceptance tests for CHANGE.md: an optional p95 latency ceiling in the gate.

They fail until the change is made. Run them on their own:

    pytest studio-3/03-compare-and-gate/test_change.py -q
"""
from __future__ import annotations

import json
import pathlib

import pytest

import starter as lab

pytestmark = pytest.mark.change

FIX = pathlib.Path(__file__).parent / "fixtures"

# Settings that switch off every other check, so only the latency ceiling can fail the gate.
ONLY_LATENCY = {"critical_ids": [], "margin": 0.1, "min_pass_rate": None, "max_cost_ratio": None}


@pytest.fixture(scope="module")
def runs():
    return {name: lab.load_run(FIX / f"{name}.json") for name in ("baseline", "candidate")}


@pytest.fixture(scope="module")
def config():
    return json.loads((FIX / "gate_config.json").read_text())


def test_default_config_has_the_new_setting_switched_off():
    assert "max_p95_latency_ratio" in lab.DEFAULT_CONFIG
    assert lab.DEFAULT_CONFIG["max_p95_latency_ratio"] is None, "off by default, like max_cost_ratio"


def test_faster_candidate_passes_a_latency_ceiling(runs, config):
    assert "max_p95_latency_ratio" in lab.DEFAULT_CONFIG
    out = lab.gate(runs["baseline"], runs["candidate"], {**config, "max_p95_latency_ratio": 1.0})
    assert out["passed"], out["reasons"]


def test_slower_candidate_fails_with_a_latency_reason(runs):
    # Swap roles: the "candidate" is now the slower system (p95 5.78 s against 3.84 s, a ratio of about 1.51).
    out = lab.gate(runs["candidate"], runs["baseline"], {**ONLY_LATENCY, "max_p95_latency_ratio": 1.2})
    assert not out["passed"]
    assert len(out["reasons"]) == 1
    assert out["reasons"][0].startswith("latency:")
    assert "1.51" in out["reasons"][0], "report the ratio with two decimals, like the cost reason"


def test_ratio_at_or_under_the_ceiling_passes(runs):
    out = lab.gate(runs["candidate"], runs["baseline"], {**ONLY_LATENCY, "max_p95_latency_ratio": 1.6})
    assert out["passed"], out["reasons"]
    assert "max_p95_latency_ratio" in lab.DEFAULT_CONFIG


def test_latency_reason_comes_after_cost(runs):
    out = lab.gate(runs["candidate"], runs["baseline"], {**ONLY_LATENCY, "max_cost_ratio": 1.0, "max_p95_latency_ratio": 1.2})
    assert [r.split(":")[0] for r in out["reasons"]] == ["cost", "latency"]
