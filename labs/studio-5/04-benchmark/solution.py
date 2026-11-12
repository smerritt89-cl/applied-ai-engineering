"""Lab 04 (Studio 5): benchmark a fine-tuned model against a frontier model. Reference solution.

Scores recorded predictions from several systems on the same frozen extraction test set:
per-field accuracy, exact match, bootstrap intervals, a paired bootstrap difference,
cost per 1,000 tasks (API or self-hosted GPU), latency percentiles, and a Markdown report.
Stdlib only.

    python solution.py fixtures/test_set.jsonl fixtures/ft-lora.json fixtures/base.json fixtures/frontier.json \
        --costs fixtures/costs.json --reference frontier
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import random
import sys
from typing import Any, Sequence

HERE = pathlib.Path(__file__).parent
FIELDS = ("is_action_item", "owner", "due_date", "priority")

Case = dict[str, Any]  # {"id", "meeting_date", "text", "gold": {field: value}}
Run = dict[str, Any]  # {"system", "model", "test_set_sha256", "predictions": [...]}
Scored = dict[str, Any]  # {"id", "parsed": bool, "fields": {field: 0 or 1}, "exact": 0 or 1}


# ----------------------------------------------------------------- loading (provided)


def load_test_set(path: str | pathlib.Path) -> list[Case]:
    """Read a JSONL test set (one case per line)."""
    lines = pathlib.Path(path).read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def load_run(path: str | pathlib.Path) -> Run:
    """Read one recorded run. It must have a non-empty "predictions" list."""
    data = json.loads(pathlib.Path(path).read_text())
    if not data.get("predictions"):
        raise ValueError(f"{path}: no predictions")
    return data


def fingerprint(cases: Sequence[Case]) -> str:
    """sha256 of every case's id, input text, and gold labels. Changes if any of them change."""
    payload = json.dumps([[c["id"], c["text"], c["gold"]] for c in cases], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile: the smallest value with at least q percent at or below it."""
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


# ----------------------------------------------------------------- scoring


def normalize(value: Any) -> Any:
    """Canonical form for comparison: strings are stripped and casefolded; everything else is unchanged."""
    if isinstance(value, str):
        return value.strip().casefold()
    return value


def field_correct(pred: dict[str, Any] | None, gold: dict[str, Any], field: str) -> bool:
    """True if the prediction's normalized value for `field` equals the gold value.

    A missing prediction (None) or a missing key is wrong. None in gold matches only None.
    """
    if pred is None or field not in pred:
        return False
    return normalize(pred[field]) == normalize(gold[field])


def score_run(cases: Sequence[Case], run: Run) -> list[Scored]:
    """Score every case, in test-set order.

    Raise ValueError if: run["test_set_sha256"] != fingerprint(cases); a prediction id is
    duplicated; or the run's ids differ from the test set's ids. Unparseable outputs
    (output is None) stay in the denominator and score 0 on every field.
    """
    if run.get("test_set_sha256") != fingerprint(cases):
        raise ValueError(f"{run.get('system')}: scored on a different test set (fingerprint mismatch)")
    by_id: dict[str, dict[str, Any]] = {}
    for p in run["predictions"]:
        if p["id"] in by_id:
            raise ValueError(f"{run.get('system')}: duplicate prediction id {p['id']}")
        by_id[p["id"]] = p
    case_ids = [c["id"] for c in cases]
    if set(by_id) != set(case_ids):
        diff = sorted(set(by_id) ^ set(case_ids))
        raise ValueError(f"{run.get('system')}: ids differ from the test set, e.g. {diff[:5]}")
    scored = []
    for c in cases:
        out = by_id[c["id"]]["output"]
        fields = {f: int(field_correct(out, c["gold"], f)) for f in FIELDS}
        scored.append({"id": c["id"], "parsed": out is not None, "fields": fields, "exact": int(all(fields.values()))})
    return scored


def field_accuracy(scored: Sequence[Scored]) -> dict[str, float]:
    """Accuracy per field over all cases (unparseable outputs count as wrong)."""
    n = len(scored)
    return {f: sum(s["fields"][f] for s in scored) / n for f in FIELDS}


def exact_match(scored: Sequence[Scored]) -> float:
    """Share of cases with every field correct."""
    return sum(s["exact"] for s in scored) / len(scored)


def parse_rate(scored: Sequence[Scored]) -> float:
    """Share of cases whose output parsed."""
    return sum(1 for s in scored if s["parsed"]) / len(scored)


# ----------------------------------------------------------------- intervals


def bootstrap_ci(values: Sequence[float], n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap interval for the mean of `values`.

    Use rng = random.Random(seed). Each replicate draws len(values) indices with
    rng.randrange(len(values)) and takes the mean. Sort the replicate means and return
    (means[int(alpha / 2 * n_boot)], means[int((1 - alpha / 2) * n_boot) - 1]).
    """
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_boot):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return means[int(alpha / 2 * n_boot)], means[int((1 - alpha / 2) * n_boot) - 1]


def paired_bootstrap_diff(
    a: Sequence[float], b: Sequence[float], n_boot: int = 2000, alpha: float = 0.05, seed: int = 0
) -> dict[str, float]:
    """Paired difference mean(a) - mean(b) with a percentile bootstrap interval.

    a and b are per-case scores in the same case order (raise ValueError if the lengths differ).
    Resample case INDICES (the same index for both systems), exactly as in bootstrap_ci, and
    compute the mean of a[i] - b[i]. Return {"diff", "lower", "upper"}.
    """
    if len(a) != len(b):
        raise ValueError("paired scores must cover the same cases")
    d = [x - y for x, y in zip(a, b)]
    lo, hi = bootstrap_ci(d, n_boot=n_boot, alpha=alpha, seed=seed)
    return {"diff": sum(d) / len(d), "lower": lo, "upper": hi}


# ----------------------------------------------------------------- cost and latency


def api_cost_per_1000(run: Run, usd_per_mtok_in: float, usd_per_mtok_out: float) -> float:
    """Mean API cost of one task (from recorded token counts) times 1,000."""
    preds = run["predictions"]
    total = sum(p["input_tokens"] * usd_per_mtok_in + p["output_tokens"] * usd_per_mtok_out for p in preds) / 1e6
    return total / len(preds) * 1000


def selfhost_cost_per_1000(gpu_hourly_usd: float, tasks_per_hour: float, utilization: float = 1.0) -> float:
    """GPU cost per 1,000 tasks when you pay for every hour but only `utilization` of it does work.

    cost = gpu_hourly_usd / (tasks_per_hour * utilization) * 1000. Raise ValueError unless
    tasks_per_hour > 0 and 0 < utilization <= 1.
    """
    if tasks_per_hour <= 0:
        raise ValueError("tasks_per_hour must be positive")
    if not 0 < utilization <= 1:
        raise ValueError("utilization must be in (0, 1]")
    return gpu_hourly_usd / (tasks_per_hour * utilization) * 1000


def cost_per_1000(run: Run, cost_spec: dict[str, Any]) -> float:
    """Dispatch on cost_spec["kind"]: "api" or "selfhost". Raise ValueError for anything else."""
    kind = cost_spec.get("kind")
    if kind == "api":
        return api_cost_per_1000(run, cost_spec["usd_per_mtok_in"], cost_spec["usd_per_mtok_out"])
    if kind == "selfhost":
        return selfhost_cost_per_1000(cost_spec["gpu_hourly_usd"], cost_spec["tasks_per_hour"], cost_spec.get("utilization", 1.0))
    raise ValueError(f"unknown cost kind: {kind!r}")


def latency_summary(run: Run) -> dict[str, float]:
    """{"p50": ..., "p95": ...} of latency_s, using percentile()."""
    lat = [p["latency_s"] for p in run["predictions"]]
    return {"p50": percentile(lat, 50), "p95": percentile(lat, 95)}


# ----------------------------------------------------------------- report


def summarize(cases: Sequence[Case], runs: Sequence[Run], costs: dict[str, Any], reference: str, seed: int = 0) -> dict[str, Any]:
    """All the numbers for the report (provided; uses your functions)."""
    scored = {r["system"]: score_run(cases, r) for r in runs}
    if reference not in scored:
        raise ValueError(f"reference system {reference!r} is not among the runs")
    rows = {}
    for r in runs:
        s = scored[r["system"]]
        exact = [x["exact"] for x in s]
        rows[r["system"]] = {
            "model": r.get("model"),
            "prompt_version": r.get("prompt_version"),
            "n": len(s),
            "parse_rate": parse_rate(s),
            "exact": exact_match(s),
            "exact_ci": bootstrap_ci(exact, seed=seed),
            "fields": field_accuracy(s),
            "cost_per_1000": cost_per_1000(r, costs[r["system"]]),
            "latency": latency_summary(r),
        }
    ref = [x["exact"] for x in scored[reference]]
    for name, s in scored.items():
        if name != reference:
            rows[name]["vs_reference"] = paired_bootstrap_diff([x["exact"] for x in s], ref, seed=seed)
    return {"reference": reference, "test_set_sha256": fingerprint(cases), "rows": rows}


def render_report(summary: dict[str, Any]) -> str:
    """Markdown report.

    Required content (the tests check it):
      - a heading line starting with "# Benchmark"
      - the first 12 characters of the test-set fingerprint
      - one table row per system, starting with "| <system> |", containing exact match as a
        percentage with one decimal and its interval, e.g. "71.3% [64.0, 78.0]", per-field
        accuracies as percentages, cost per 1,000 as "$1.23", and p50 / p95 latency in seconds
      - for every non-reference system, a line "<system> vs <reference>: +4.7 points [-2.0, +11.3]"
        (signed, one decimal, in percentage points)
      - a closing line reminding the reader that intervals cover test-set sampling only
    """
    rows = summary["rows"]
    ref = summary["reference"]
    out = [
        "# Benchmark: extraction on a frozen test set",
        "",
        f"Test set fingerprint: `{summary['test_set_sha256'][:12]}`. Reference system: `{ref}`.",
        "",
        "| System | n | Parsed | Exact match [95% CI] | " + " | ".join(FIELDS) + " | Cost / 1,000 | p50 / p95 latency |",
        "|---|---|---|---|" + "---|" * len(FIELDS) + "---|---|",
    ]
    for name, r in rows.items():
        lo, hi = r["exact_ci"]
        fields = " | ".join(f"{100 * r['fields'][f]:.1f}%" for f in FIELDS)
        out.append(
            f"| {name} | {r['n']} | {100 * r['parse_rate']:.1f}% | {100 * r['exact']:.1f}% [{100 * lo:.1f}, {100 * hi:.1f}] | "
            f"{fields} | ${r['cost_per_1000']:.2f} | {r['latency']['p50']:.2f}s / {r['latency']['p95']:.2f}s |"
        )
    out.append("")
    out.append("Paired differences in exact match (percentage points, 95% bootstrap interval):")
    out.append("")
    for name, r in rows.items():
        if name == ref:
            continue
        v = r["vs_reference"]
        out.append(f"- {name} vs {ref}: {100 * v['diff']:+.1f} points [{100 * v['lower']:+.1f}, {100 * v['upper']:+.1f}]")
    out.append("")
    out.append(
        "Intervals reflect sampling of test cases only. They do not cover run-to-run variation, "
        "prompt choices, or traffic that differs from the test set."
    )
    return "\n".join(out) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """CLI (provided)."""
    ap = argparse.ArgumentParser(description="Benchmark recorded extraction runs on a frozen test set.")
    ap.add_argument("test_set")
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--costs", required=True)
    ap.add_argument("--reference", required=True, help="system name to compare the others against")
    ap.add_argument("--out", help="write the Markdown report here as well as to stdout")
    args = ap.parse_args(argv)
    cases = load_test_set(args.test_set)
    runs = [load_run(p) for p in args.runs]
    costs = json.loads(pathlib.Path(args.costs).read_text())
    report = render_report(summarize(cases, runs, costs, args.reference))
    if args.out:
        pathlib.Path(args.out).write_text(report)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
