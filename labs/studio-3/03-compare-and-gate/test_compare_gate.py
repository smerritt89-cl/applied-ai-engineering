"""Tests for Studio 3 lab 03. All offline: they check the statistics against known values
and the gate against recorded fixtures. No API key needed.

Run:  pytest studio-3/03-compare-and-gate -q
"""
from __future__ import annotations

import copy
import json
import math
import pathlib

import pytest

import starter as lab

FIX = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def runs():
    return {
        name: lab.load_run(FIX / f"{name}.json")
        for name in ("baseline", "candidate", "candidate_regressed")
    }


@pytest.fixture(scope="module")
def config():
    return json.loads((FIX / "gate_config.json").read_text())


def make_pairs(wins: int, losses: int, both_pass: int, both_fail: int) -> list[dict]:
    """Synthetic aligned pairs, one cluster per question."""
    rows = [(1, 0)] * wins + [(0, 1)] * losses + [(1, 1)] * both_pass + [(0, 0)] * both_fail
    return [{"id": f"x{i:04d}", "cluster": f"c{i:04d}", "base": b, "cand": c} for i, (c, b) in enumerate(rows)]


# ----------------------------------------------------------------- one system


def test_pass_rate_on_fixtures(runs):
    assert lab.pass_rate(runs["baseline"]["results"]) == pytest.approx(204 / 240)
    assert lab.pass_rate(runs["candidate"]["results"]) == pytest.approx(210 / 240)


@pytest.mark.parametrize(
    "k, n, lo, hi",
    [
        (164, 200, 0.760884, 0.867054),  # the lesson's worked example
        (48, 50, 0.865397, 0.988961),  # Wald would give an upper bound above 1
        (50, 50, 0.928650, 1.0),  # Wald would give zero width
        (0, 10, 0.0, 0.277533),
    ],
)
def test_wilson_known_values(k, n, lo, hi):
    got = lab.wilson_interval(k, n)
    assert got[0] == pytest.approx(lo, abs=1e-5)
    assert got[1] == pytest.approx(hi, abs=1e-5)


def test_wilson_rejects_empty():
    with pytest.raises(ValueError):
        lab.wilson_interval(0, 0)


def test_cost_per_success():
    results = [
        {"passed": True, "cost_usd": 0.01},
        {"passed": False, "cost_usd": 0.03},
        {"passed": True, "cost_usd": 0.02},
    ]
    assert lab.cost_per_success(results) == pytest.approx(0.03), "failed calls still cost money: 0.06 / 2"
    assert lab.cost_per_success([{"passed": False, "cost_usd": 0.01}]) == math.inf


# ----------------------------------------------------------------- bootstrap


def test_cluster_bootstrap_is_reproducible_and_brackets_the_estimate(runs):
    res = runs["baseline"]["results"]
    a = lab.cluster_bootstrap_ci(res, lab.pass_rate, n_boot=500, seed=3)
    b = lab.cluster_bootstrap_ci(res, lab.pass_rate, n_boot=500, seed=3)
    assert a == b, "same seed must give the same interval"
    assert a[0] < 0.85 < a[1]


def test_cluster_bootstrap_matches_clt_when_clusters_are_singletons():
    """With one question per cluster, the cluster bootstrap is the ordinary bootstrap,
    and for 164/200 it should land near the CLT interval [0.767, 0.873]."""
    items = [{"cluster": f"c{i}", "passed": i < 164} for i in range(200)]
    lo, hi = lab.cluster_bootstrap_ci(items, lab.pass_rate, n_boot=2000, seed=0)
    assert lo == pytest.approx(0.767, abs=0.015)
    assert hi == pytest.approx(0.873, abs=0.015)


def test_clustering_widens_the_interval():
    """40 clusters of 5 identical outcomes carry about as much information as 40 questions."""
    clustered = [{"cluster": f"c{i // 5}", "passed": (i // 5) < 30} for i in range(200)]
    lo, hi = lab.cluster_bootstrap_ci(clustered, lab.pass_rate, n_boot=2000, seed=0)
    w_lo, w_hi = lab.wilson_interval(150, 200)
    assert (hi - lo) > 1.6 * (w_hi - w_lo), "cluster resampling must respect the groups"


def test_bootstrap_uses_the_documented_percentile_positions():
    items = [{"cluster": f"c{i}", "passed": True} for i in range(10)]
    seen = []

    def stat(sample):
        seen.append(len(sample))
        return float(len(seen))  # replicate number, so sorted values are 1..n_boot

    lo, hi = lab.cluster_bootstrap_ci(items, stat, n_boot=200, alpha=0.1, seed=0)
    assert len(seen) == 200 and set(seen) == {10}, "each replicate draws as many clusters as there are"
    assert (lo, hi) == (11.0, 190.0), "lo = values[int(alpha/2*n_boot)], hi = values[int((1-alpha/2)*n_boot) - 1]"


# ----------------------------------------------------------------- pairing


def test_align_pairs_by_id_and_sorts(runs):
    base = runs["baseline"]["results"]
    shuffled = list(reversed(runs["candidate"]["results"]))
    pairs = lab.align(base, shuffled)
    assert [p["id"] for p in pairs] == sorted(r["id"] for r in base)
    assert set(pairs[0]) == {"id", "cluster", "base", "cand"}
    assert all(p["base"] in (0, 1) and p["cand"] in (0, 1) for p in pairs)


def test_align_rejects_mismatches(runs):
    base = runs["baseline"]["results"]
    with pytest.raises(ValueError):
        lab.align(base, base[:-1])
    with pytest.raises(ValueError):
        lab.align(base, base[:-1] + [base[0]])  # duplicate id
    moved = copy.deepcopy(base)
    moved[0]["cluster"] = "article-99"
    with pytest.raises(ValueError):
        lab.align(base, moved)


def test_paired_difference_known_values():
    d = lab.paired_difference(make_pairs(wins=12, losses=4, both_pass=150, both_fail=34))
    assert d["mean"] == pytest.approx(0.04)
    assert d["se"] == pytest.approx(0.0198487, abs=1e-6), "sample SD of d (n - 1) over sqrt(n)"
    assert d["lower"] == pytest.approx(0.04 - 1.96 * 0.0198487, abs=1e-6)
    assert d["upper"] == pytest.approx(0.04 + 1.96 * 0.0198487, abs=1e-6)


def test_pairing_beats_the_unpaired_standard_error():
    pairs = make_pairs(wins=24, losses=16, both_pass=140, both_fail=20)
    paired = lab.paired_difference(pairs)["se"]
    unpaired = math.sqrt(0.82 * 0.18 / 200 + 0.78 * 0.22 / 200)
    assert paired == pytest.approx(0.0315751, abs=1e-6)
    assert paired < unpaired


@pytest.mark.parametrize(
    "wins, losses, p",
    [(24, 16, 0.268187), (12, 4, 0.076813), (5, 0, 0.0625), (0, 5, 0.0625), (3, 3, 1.0), (0, 0, 1.0)],
)
def test_mcnemar_exact_known_values(wins, losses, p):
    out = lab.mcnemar_exact(make_pairs(wins=wins, losses=losses, both_pass=20, both_fail=5))
    assert (out["wins"], out["losses"]) == (wins, losses)
    assert out["p"] == pytest.approx(p, abs=1e-6)


def test_fixture_comparison_numbers(runs):
    pairs = lab.align(runs["baseline"]["results"], runs["candidate"]["results"])
    m = lab.mcnemar_exact(pairs)
    assert (m["wins"], m["losses"]) == (12, 6)
    assert m["p"] == pytest.approx(0.237885, abs=1e-6)
    d = lab.paired_difference(pairs)
    assert d["mean"] == pytest.approx(0.025)
    assert d["lower"] < 0 < d["upper"], "a 2.5-point gain on 240 questions is not established"


# ----------------------------------------------------------------- the gate


def test_gate_passes_the_good_candidate(runs, config):
    out = lab.gate(runs["baseline"], runs["candidate"], config)
    assert out["passed"], out["reasons"]
    assert out["reasons"] == []
    assert out["summary"]["mcnemar"]["wins"] == 12


def test_gate_fails_the_regressed_candidate(runs, config):
    out = lab.gate(runs["baseline"], runs["candidate_regressed"], config)
    assert not out["passed"]
    assert out["reasons"][0].startswith("possible regression")
    assert any(r.startswith("pass rate floor") for r in out["reasons"]), "Wilson lower bound 0.745 is below 0.80"


def test_gate_checks_critical_cases_first(runs, config):
    cand = copy.deepcopy(runs["candidate"])
    for r in cand["results"]:
        if r["id"] == "q050":
            r["passed"] = False
    out = lab.gate(runs["baseline"], cand, config)
    assert not out["passed"]
    assert out["reasons"][0] == "critical failed: q050"


def test_gate_rejects_unknown_critical_id(runs, config):
    with pytest.raises(ValueError):
        lab.gate(runs["baseline"], runs["candidate"], {**config, "critical_ids": ["q999"]})


def test_gate_margin_is_configurable(runs, config):
    strict = lab.gate(runs["baseline"], runs["candidate"], {**config, "margin": 0.0})
    assert not strict["passed"], "with zero margin, an interval that includes zero fails"
    assert strict["reasons"][0].startswith("possible regression")


def test_gate_cluster_bootstrap_option(runs, config):
    out = lab.gate(runs["baseline"], runs["candidate"], {**config, "cluster_bootstrap": True, "margin": 0.015})
    plain = lab.gate(runs["baseline"], runs["candidate"], {**config, "margin": 0.015})
    assert plain["passed"], "the iid lower bound (about -0.010) clears a 1.5-point margin"
    assert not out["passed"], "the cluster-bootstrap lower bound (about -0.02) does not"


def test_gate_cost_ceiling(runs, config):
    out = lab.gate(runs["candidate"], runs["baseline"], {**config, "critical_ids": [], "margin": 0.1, "min_pass_rate": None})
    assert not out["passed"], "swapping roles: the 'candidate' now costs about twice as much per success"
    assert out["reasons"] == [r for r in out["reasons"] if r.startswith("cost")]


def test_defaults_apply_without_config(runs):
    out = lab.gate(runs["baseline"], runs["candidate"])
    assert out["passed"]


def test_cli_exit_codes(runs, capsys):
    ok = lab.main([str(FIX / "baseline.json"), str(FIX / "candidate.json"), "--config", str(FIX / "gate_config.json")])
    assert ok == 0
    bad = lab.main([str(FIX / "baseline.json"), str(FIX / "candidate_regressed.json"), "--config", str(FIX / "gate_config.json")])
    assert bad == 1
    assert "GATE: FAIL" in capsys.readouterr().out
