"""Regenerate the recorded results in this folder (deterministic).

The fixtures stand in for two real eval runs on the same 240-question support-triage
suite: 60 help-center articles with 4 questions each. Run from the lab folder:
    python fixtures/make_fixtures.py
"""
import json
import pathlib
import random

HERE = pathlib.Path(__file__).parent
rng = random.Random(2026)

ids = [f"q{i:03d}" for i in range(1, 241)]
cluster = {q: f"article-{(i // 4) + 1:02d}" for i, q in enumerate(ids)}

# Baseline: 6 whole articles fail (24 questions) plus 12 scattered failures -> 204 of 240 pass.
failing_articles = [f"article-{n:02d}" for n in (5, 12, 19, 33, 41, 57)]
base_fail = {q for q in ids if cluster[q] in failing_articles}
others = [q for q in ids if q not in base_fail]
base_fail |= set(rng.sample(others, 12))
base = {q: q not in base_fail for q in ids}

CRITICAL = ["q001", "q002", "q050", "q101", "q200"]
for q in CRITICAL:
    assert base[q], q

# Good candidate: fixes 2 failing articles (8 questions) and 4 scattered failures, breaks 6 passes.
fixed = [q for q in ids if cluster[q] in ("article-12", "article-41")]
fixed += rng.sample(sorted(q for q in base_fail if q not in fixed and cluster[q] not in failing_articles), 4)
breakable = sorted(q for q in ids if base[q] and q not in CRITICAL)
broken = rng.sample(breakable, 6)
cand = dict(base)
for q in fixed:
    cand[q] = True
for q in broken:
    cand[q] = False

# Regressed candidate: fixes 3, breaks 15.
bad = dict(base)
for q in rng.sample(sorted(base_fail), 3):
    bad[q] = True
for q in rng.sample(breakable, 15):
    bad[q] = False


def run(system, model, prompt_version, passed, cost_range, latency_range):
    results = []
    for q in ids:
        results.append({
            "id": q,
            "cluster": cluster[q],
            "passed": passed[q],
            "cost_usd": round(rng.uniform(*cost_range), 5),
            "latency_s": round(rng.uniform(*latency_range), 2),
        })
    return {
        "system": system,
        "model": model,
        "prompt_version": prompt_version,
        "dataset": "support-triage-v3",
        "grader": "triage-grader-v2",
        "trials_per_question": 1,
        "recorded": "2026-11-11",
        "results": results,
    }


files = {
    "baseline.json": run("baseline", "claude-opus-5-5", "triage-v12", base, (0.004, 0.008), (2.0, 6.0)),
    "candidate.json": run("candidate", "claude-sonnet-5-5", "triage-v13", cand, (0.002, 0.004), (1.0, 4.0)),
    "candidate_regressed.json": run("candidate-regressed", "claude-sonnet-5-5", "triage-v13b", bad, (0.002, 0.004), (1.0, 4.0)),
}
for name, data in files.items():
    (HERE / name).write_text(json.dumps(data, indent=1) + "\n")
(HERE / "gate_config.json").write_text(json.dumps({
    "margin": 0.03,
    "critical_ids": CRITICAL,
    "min_pass_rate": 0.80,
    "max_cost_ratio": 1.0,
    "cluster_bootstrap": False,
    "z": 1.96,
}, indent=2) + "\n")
print({n: sum(r["passed"] for r in d["results"]) for n, d in files.items()})
