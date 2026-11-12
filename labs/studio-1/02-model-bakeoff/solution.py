"""Lab 02, reference solution: a tiny model bake-off harness. Try starter.py first."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import pathlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

HERE = pathlib.Path(__file__).parent

# USD per million tokens (input, output), standard tier, short prompts.
# Snapshot 2026-11-11 from each provider's pricing page; CHECK BEFORE RELYING ON IT.
#   Claude:  https://platform.claude.com/docs/en/about-claude/pricing
#   OpenAI:  https://developers.openai.com/api/docs/pricing
#   Gemini:  https://aistudio.google.com/docs/pricing   (Flash rates through 2026-12-31)
#   xAI:     https://docs.x.ai/docs/models              (rates below 200K-token prompts)
PRICES: dict[str, dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50},
    "gpt-6.1-sol": {"input": 2.00, "output": 10.00},
    "gpt-6-luna": {"input": 0.10, "output": 0.50},
    "gemini-3.8-flash": {"input": 0.75, "output": 3.75},
    "grok-4.3": {"input": 1.25, "output": 2.50},
}

DEFAULT_CLAUDE_MODELS = ["claude-sonnet-5-5", "claude-haiku-5-5"]
OPTIONAL_MODELS = {"openai": "gpt-6.1-sol", "gemini": "gemini-3.8-flash", "xai": "grok-4.3"}


@dataclass
class Candidate:
    provider: str
    model: str
    # call(prompt, max_tokens) -> (text, input_tokens, output_tokens, stop_reason)
    call: Callable[[str, int], tuple[str, int, int, str]]


@dataclass
class Result:
    prompt_id: str
    provider: str
    model: str
    output: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    cost_usd: float = 0.0
    stop_reason: str = ""
    error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------- provider adapters (provided)
# Each adapter is deliberately minimal. Read the provider's docs before extending one.


def claude_caller(client: Any, model: str) -> Callable[[str, int], tuple[str, int, int, str]]:
    """Official anthropic SDK, Messages API."""

    def call(prompt: str, max_tokens: int):
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}]
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return text, resp.usage.input_tokens, resp.usage.output_tokens, resp.stop_reason

    return call


def openai_responses_caller(client: Any, model: str) -> Callable[[str, int], tuple[str, int, int, str]]:
    """OpenAI's Responses API via the official openai SDK. xAI documents the same endpoint
    at base_url https://api.x.ai/v1, so this adapter serves both."""

    def call(prompt: str, max_tokens: int):
        resp = client.responses.create(model=model, input=prompt, max_output_tokens=max_tokens)
        usage = getattr(resp, "usage", None)
        return (
            resp.output_text or "",
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
            str(getattr(resp, "status", "")),
        )

    return call


def openai_chat_caller(client: Any, model: str) -> Callable[[str, int], tuple[str, int, int, str]]:
    """Chat Completions shape, used for Gemini's documented OpenAI-compatible endpoint.
    max_tokens is not sent, to stay within what the compatibility page documents."""

    def call(prompt: str, max_tokens: int):
        resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}])
        choice = resp.choices[0]
        usage = getattr(resp, "usage", None)
        return (
            choice.message.content or "",
            int(getattr(usage, "prompt_tokens", 0) or 0),
            int(getattr(usage, "completion_tokens", 0) or 0),
            str(getattr(choice, "finish_reason", "")),
        )

    return call


def available_candidates(env: dict[str, str] | None = None, claude_models: list[str] | None = None) -> list[Candidate]:
    """Claude models always (needs ANTHROPIC_API_KEY); other providers only if their key is set
    and the `openai` package is installed. Missing keys are skipped, not errors."""
    env = dict(os.environ) if env is None else env
    out: list[Candidate] = []
    if env.get("ANTHROPIC_API_KEY"):
        import anthropic

        client = anthropic.Anthropic()
        for m in claude_models or DEFAULT_CLAUDE_MODELS:
            out.append(Candidate("anthropic", m, claude_caller(client, m)))
    try:
        from openai import OpenAI  # optional dependency: pip install openai
    except ImportError:
        OpenAI = None  # noqa: N806
    if OpenAI is not None:
        if env.get("OPENAI_API_KEY"):
            m = OPTIONAL_MODELS["openai"]
            out.append(Candidate("openai", m, openai_responses_caller(OpenAI(api_key=env["OPENAI_API_KEY"]), m)))
        if env.get("GEMINI_API_KEY"):
            m = OPTIONAL_MODELS["gemini"]
            client = OpenAI(
                api_key=env["GEMINI_API_KEY"], base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
            )
            out.append(Candidate("google", m, openai_chat_caller(client, m)))
        if env.get("XAI_API_KEY"):
            m = OPTIONAL_MODELS["xai"]
            client = OpenAI(api_key=env["XAI_API_KEY"], base_url="https://api.x.ai/v1")
            out.append(Candidate("xai", m, openai_responses_caller(client, m)))
    return out


def load_prompts(path: pathlib.Path = HERE / "prompts.json") -> list[dict[str, Any]]:
    return json.loads(path.read_text())


# ----------------------------------------------------------------- the harness (the TODOs in starter.py)


def cost_usd(model: str, input_tokens: int, output_tokens: int, prices: dict[str, dict[str, float]] = PRICES) -> float:
    p = prices[model]
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


def run_one(
    candidate: Candidate,
    prompt_row: dict[str, Any],
    *,
    max_tokens: int = 4096,
    clock: Callable[[], float] = time.perf_counter,
    prices: dict[str, dict[str, float]] = PRICES,
) -> Result:
    r = Result(prompt_id=prompt_row["id"], provider=candidate.provider, model=candidate.model)
    start = clock()
    try:
        text, tin, tout, stop = candidate.call(prompt_row["prompt"], max_tokens)
    except Exception as exc:  # noqa: BLE001 (a failure is a data point, not a crash)
        r.latency_s = clock() - start
        r.error = f"{type(exc).__name__}: {exc}"
        return r
    r.latency_s = clock() - start
    r.output, r.input_tokens, r.output_tokens, r.stop_reason = text, tin, tout, stop
    r.cost_usd = cost_usd(candidate.model, tin, tout, prices)
    return r


def run_bakeoff(candidates: list[Candidate], prompts: list[dict[str, Any]], **kwargs: Any) -> list[Result]:
    return [run_one(c, p, **kwargs) for p in prompts for c in candidates]


def auto_score(result: Result, must_include: list[str]) -> float:
    if result.error:
        return 0.0
    if not must_include:
        return 1.0
    text = result.output.lower()
    hits = sum(1 for term in must_include if term.lower() in text)
    return hits / len(must_include)


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[k - 1]


def summarize(results: list[Result], scores: dict[tuple[str, str], float]) -> dict[str, dict[str, Any]]:
    by_model: dict[str, list[Result]] = {}
    for r in results:
        by_model.setdefault(r.model, []).append(r)
    summary: dict[str, dict[str, Any]] = {}
    for model, rs in by_model.items():
        ok = [r for r in rs if not r.error]
        lat = [r.latency_s for r in ok]
        total_cost = sum(r.cost_usd for r in rs)
        summary[model] = {
            "provider": rs[0].provider,
            "n": len(rs),
            "errors": len(rs) - len(ok),
            "mean_score": sum(scores.get((r.prompt_id, model), 0.0) for r in rs) / len(rs),
            "total_cost_usd": total_cost,
            "cost_per_task_usd": total_cost / len(rs),
            "p50_latency_s": percentile(lat, 50),
            "p95_latency_s": percentile(lat, 95),
            "mean_output_tokens": (sum(r.output_tokens for r in ok) / len(ok)) if ok else 0.0,
        }
    return summary


def pick_winner(summary: dict[str, dict[str, Any]], quality_bar: float) -> str | None:
    passing = [(s["cost_per_task_usd"], s["p95_latency_s"] or float("inf"), m)
               for m, s in summary.items() if s["mean_score"] >= quality_bar and s["errors"] == 0]
    if not passing:
        return None
    return min(passing)[2]


CSV_COLUMNS = [
    "prompt_id", "provider", "model", "auto_score", "human_score", "latency_s", "input_tokens",
    "output_tokens", "cost_usd", "stop_reason", "error", "output",
]


def write_csv(results: list[Result], scores: dict[tuple[str, str], float], path: pathlib.Path) -> None:
    rows = sorted(results, key=lambda r: (r.prompt_id, r.model))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            d = asdict(r)
            w.writerow({
                **{k: d[k] for k in CSV_COLUMNS if k in d},
                "auto_score": round(scores.get((r.prompt_id, r.model), 0.0), 3),
                "human_score": "",
                "latency_s": round(r.latency_s, 3),
                "cost_usd": f"{r.cost_usd:.6f}",
            })


# ----------------------------------------------------------------- rescoring from your CSV (provided)


def load_scores_from_csv(path: pathlib.Path) -> tuple[list[Result], dict[tuple[str, str], float]]:
    """Read a results CSV back. Uses human_score (0 to 1) where you filled it in, else auto_score."""
    results, scores = [], {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            r = Result(
                prompt_id=row["prompt_id"], provider=row["provider"], model=row["model"], output=row["output"],
                input_tokens=int(row["input_tokens"] or 0), output_tokens=int(row["output_tokens"] or 0),
                latency_s=float(row["latency_s"] or 0), cost_usd=float(row["cost_usd"] or 0),
                stop_reason=row["stop_reason"], error=row["error"],
            )
            results.append(r)
            raw = row["human_score"].strip() or row["auto_score"]
            scores[(r.prompt_id, r.model)] = float(raw)
    return results, scores


def print_summary(summary: dict[str, dict[str, Any]], quality_bar: float) -> None:
    print(f"\n{'model':20s} {'score':>6s} {'err':>4s} {'$/task':>10s} {'p50 s':>7s} {'p95 s':>7s} {'out tok':>8s}")
    for m, s in sorted(summary.items(), key=lambda kv: -kv[1]["mean_score"]):
        p50 = f"{s['p50_latency_s']:.2f}" if s["p50_latency_s"] is not None else "-"
        p95 = f"{s['p95_latency_s']:.2f}" if s["p95_latency_s"] is not None else "-"
        print(f"{m:20s} {s['mean_score']:6.2f} {s['errors']:4d} {s['cost_per_task_usd']:10.6f} "
              f"{p50:>7s} {p95:>7s} {s['mean_output_tokens']:8.0f}")
    winner = pick_winner(summary, quality_bar)
    print(f"\nCheapest model at or above a mean score of {quality_bar}: {winner or 'none'}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Run the same prompts through several models.")
    ap.add_argument("--models", nargs="*", help="Claude model ids to compare (default: Sonnet and Haiku 5.5)")
    ap.add_argument("--out", default=str(HERE / "results.csv"))
    ap.add_argument("--bar", type=float, default=0.8, help="quality bar on mean score (0 to 1)")
    ap.add_argument("--rescore", help="skip the API; re-summarize an edited results CSV")
    args = ap.parse_args(argv)

    if args.rescore:
        results, scores = load_scores_from_csv(pathlib.Path(args.rescore))
        print_summary(summarize(results, scores), args.bar)
        return

    candidates = available_candidates(claude_models=args.models)
    if not candidates:
        raise SystemExit("No API keys found. Set ANTHROPIC_API_KEY in labs/.env (others are optional).")
    print("Candidates:", ", ".join(f"{c.provider}/{c.model}" for c in candidates))
    prompts = load_prompts()
    results = run_bakeoff(candidates, prompts)
    must = {p["id"]: p.get("must_include", []) for p in prompts}
    scores = {(r.prompt_id, r.model): auto_score(r, must[r.prompt_id]) for r in results}
    write_csv(results, scores, pathlib.Path(args.out))
    print(f"Wrote {args.out}. Total cost ${sum(r.cost_usd for r in results):.4f}")
    print_summary(summarize(results, scores), args.bar)


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv(HERE.parent.parent / ".env")
    except ImportError:
        pass
    main()
