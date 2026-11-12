"""Lab 03 (Studio 3): compare two systems and gate a release. Your work goes in the functions marked TODO.

Reads recorded per-question results for a baseline and a candidate, computes pass rates
with Wilson and cluster-bootstrap intervals, the paired difference with McNemar's exact
test, and a pass/fail gate. Stdlib only.

    python starter.py fixtures/baseline.json fixtures/candidate.json --config fixtures/gate_config.json
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import random
import sys
from typing import Any, Callable, Sequence

HERE = pathlib.Path(__file__).parent

Result = dict[str, Any]  # {"id", "cluster", "passed", "cost_usd", "latency_s"}
Pair = dict[str, Any]  # {"id", "cluster", "base": 0 or 1, "cand": 0 or 1}


# ----------------------------------------------------------------- loading


def load_run(path: str | pathlib.Path) -> dict[str, Any]:
    """Load one recorded run. It must have a non-empty "results" list."""
    data = json.loads(pathlib.Path(path).read_text())
    if not data.get("results"):
        raise ValueError(f"{path}: no results")
    return data


# ----------------------------------------------------------------- one system


def pass_rate(results: Sequence[Result]) -> float:
    """Fraction of results with passed == True."""
    # TODO: implement pass_rate (see the README step and the docstring)
    raise NotImplementedError


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes out of n, clipped to [0, 1]. Raise ValueError if n <= 0."""
    # TODO: implement wilson_interval (see the README step and the docstring)
    raise NotImplementedError


def cluster_bootstrap_ci(
    items: Sequence[dict[str, Any]],
    stat: Callable[[list[dict[str, Any]]], float],
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap interval that resamples whole clusters.

    Group items by item["cluster"] (keep first-appearance order of clusters). Each replicate
    draws len(clusters) clusters with replacement using random.Random(seed), pools their
    items, and applies stat. Sort the replicate values and return
    (values[int(alpha / 2 * n_boot)], values[int((1 - alpha / 2) * n_boot) - 1]).
    """
    # TODO: implement cluster_bootstrap_ci (see the README step and the docstring)
    raise NotImplementedError


def cost_per_success(results: Sequence[Result]) -> float:
    """Total cost_usd divided by the number of passes (inf if there are none)."""
    # TODO: implement cost_per_success (see the README step and the docstring)
    raise NotImplementedError


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (provided): the smallest value with at least q percent at or below it."""
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


# ----------------------------------------------------------------- two systems


def align(base: Sequence[Result], cand: Sequence[Result]) -> list[Pair]:
    """Pair results by question id, sorted by id.

    Raise ValueError if either side has a duplicate id, if the id sets differ, or if a
    question's cluster differs between the two runs. Each pair is
    {"id", "cluster", "base": 1 or 0, "cand": 1 or 0}.
    """
    # TODO: implement align (see the README step and the docstring)
    raise NotImplementedError


def paired_difference(pairs: Sequence[Pair], z: float = 1.96) -> dict[str, float]:
    """Mean of d = cand - base, its standard error (sample SD with n - 1, over sqrt(n)),
    and the normal-approximation interval. Returns {"mean", "se", "lower", "upper"}."""
    # TODO: implement paired_difference (see the README step and the docstring)
    raise NotImplementedError


def mcnemar_exact(pairs: Sequence[Pair]) -> dict[str, float]:
    """Exact two-sided McNemar test.

    wins = candidate passed and baseline failed; losses = the reverse.
    p = min(1, 2 * P(X <= min(wins, losses))) for X ~ Binomial(wins + losses, 0.5); p = 1.0 if
    there are no discordant questions. Returns {"wins", "losses", "p"}.
    """
    # TODO: implement mcnemar_exact (see the README step and the docstring)
    raise NotImplementedError


def cluster_diff_ci(pairs: Sequence[Pair], n_boot: int = 2000, seed: int = 0) -> tuple[float, float]:
    """Cluster-bootstrap interval for the mean paired difference (provided; uses your functions)."""
    return cluster_bootstrap_ci(pairs, lambda s: sum(p["cand"] - p["base"] for p in s) / len(s), n_boot=n_boot, seed=seed)


# ----------------------------------------------------------------- the gate


DEFAULT_CONFIG: dict[str, Any] = {
    "margin": 0.03,  # fail if the paired lower bound is below -margin
    "critical_ids": [],  # must-pass questions
    "min_pass_rate": None,  # optional floor on the candidate's Wilson LOWER bound
    "max_cost_ratio": None,  # optional ceiling on candidate / baseline cost per success
    "cluster_bootstrap": False,  # if True, take the lower bound from cluster_diff_ci instead
    "z": 1.96,
}


def gate(base_run: dict[str, Any], cand_run: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Decide whether the candidate may ship.

    Merge config over DEFAULT_CONFIG. Align the runs (align raises on mismatches). Raise
    ValueError if a critical id is not among the candidate's results. Collect
    reasons, in this order:
      1. "critical failed: <id>" for each critical id (in config order) the candidate fails.
      2. "possible regression: ..." if the paired lower bound < -margin. The lower bound is
         paired_difference(...)["lower"], or cluster_diff_ci(pairs)[0] when cluster_bootstrap is True.
      3. "pass rate floor: ..." if min_pass_rate is set and the candidate's Wilson lower bound is below it.
      4. "cost: ..." if max_cost_ratio is set and cand cost per success / base cost per success exceeds it.
    Return {"passed": no reasons, "reasons": [...], "summary": summarize(...)}.
    """
    # TODO: implement gate (see the README step and the docstring)
    raise NotImplementedError


def summarize(base_run: dict[str, Any], cand_run: dict[str, Any], pairs: Sequence[Pair], z: float = 1.96) -> dict[str, Any]:
    """Numbers for the report (provided)."""
    out: dict[str, Any] = {}
    for name, run in (("baseline", base_run), ("candidate", cand_run)):
        res = run["results"]
        k = sum(1 for r in res if r["passed"])
        out[name] = {
            "model": run.get("model"),
            "prompt_version": run.get("prompt_version"),
            "pass_rate": k / len(res),
            "wilson": wilson_interval(k, len(res), z),
            "cluster_ci": cluster_bootstrap_ci(res, pass_rate),
            "cost_per_success": cost_per_success(res),
            "p95_latency_s": percentile([r["latency_s"] for r in res], 95),
        }
    out["paired"] = paired_difference(pairs, z)
    out["paired_cluster_ci"] = cluster_diff_ci(pairs)
    out["mcnemar"] = mcnemar_exact(pairs)
    out["n"] = len(pairs)
    out["dataset"] = (base_run.get("dataset"), cand_run.get("dataset"))
    return out


def format_report(result: dict[str, Any]) -> str:
    """Human-readable report (provided)."""
    s = result["summary"]
    lines = [f"Questions: {s['n']}   dataset: {s['dataset'][0]} vs {s['dataset'][1]}"]
    for name in ("baseline", "candidate"):
        b = s[name]
        lines.append(
            f"{name:9}  {b['model']} / {b['prompt_version']}: pass {b['pass_rate']:.3f}  "
            f"Wilson [{b['wilson'][0]:.3f}, {b['wilson'][1]:.3f}]  cluster [{b['cluster_ci'][0]:.3f}, {b['cluster_ci'][1]:.3f}]  "
            f"cost/success ${b['cost_per_success']:.5f}  p95 {b['p95_latency_s']:.2f}s"
        )
    p, m = s["paired"], s["mcnemar"]
    lines.append(
        f"paired diff {p['mean']:+.3f}  95% [{p['lower']:+.3f}, {p['upper']:+.3f}]  "
        f"cluster [{s['paired_cluster_ci'][0]:+.3f}, {s['paired_cluster_ci'][1]:+.3f}]  "
        f"McNemar wins {m['wins']} losses {m['losses']} p={m['p']:.3f}"
    )
    lines.append("GATE: PASS" if result["passed"] else "GATE: FAIL")
    lines.extend(f"  - {r}" for r in result["reasons"])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI (provided). Exit code 0 if the gate passes, 1 if it fails."""
    ap = argparse.ArgumentParser(description="Compare two recorded eval runs and apply a release gate.")
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    ap.add_argument("--config", help="JSON file with gate settings")
    ap.add_argument("--margin", type=float, help="override the non-inferiority margin, e.g. 0.02")
    args = ap.parse_args(argv)
    config = json.loads(pathlib.Path(args.config).read_text()) if args.config else {}
    if args.margin is not None:
        config["margin"] = args.margin
    result = gate(load_run(args.baseline), load_run(args.candidate), config)
    print(format_report(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
