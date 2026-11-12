"""Lab 02: a tiny model bake-off harness.

The provider adapters, CLI, and CSV rescoring are written for you. Your job is the
harness logic: pricing, running, scoring, aggregating, choosing, and writing the CSV.
Fill in every function marked TODO, then run:
    pytest studio-1/02-model-bakeoff -q
"""
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


# ----------------------------------------------------------------- the harness (your TODOs)


def cost_usd(model: str, input_tokens: int, output_tokens: int, prices: dict[str, dict[str, float]] = PRICES) -> float:
    """USD cost of one call: tokens times prices[model] per million tokens.
    Unknown models raise KeyError (never silently price a model at zero)."""
    # TODO: implement (README step for cost_usd)
    raise NotImplementedError


def run_one(
    candidate: Candidate,
    prompt_row: dict[str, Any],
    *,
    max_tokens: int = 4096,
    clock: Callable[[], float] = time.perf_counter,
    prices: dict[str, dict[str, float]] = PRICES,
) -> Result:
    """Run one candidate on one prompt and return a Result.

    - Time the call with clock() (injected so tests are deterministic).
    - On success, fill output, input_tokens, output_tokens, stop_reason, latency_s, cost_usd.
    - If candidate.call raises ANY exception, do not crash the bake-off: return a Result
      with error = "ExceptionType: message", latency_s set, and cost_usd 0.
    """
    # TODO: implement (README step for run_one)
    raise NotImplementedError


def run_bakeoff(candidates: list[Candidate], prompts: list[dict[str, Any]], **kwargs: Any) -> list[Result]:
    """Run every candidate on every prompt (prompt-major order: all models on p1, then p2, ...).
    Pass **kwargs through to run_one."""
    # TODO: implement (README step for run_bakeoff)
    raise NotImplementedError


def auto_score(result: Result, must_include: list[str]) -> float:
    """A crude automatic check: the fraction of must_include terms that appear in the
    output, case-insensitive. Errors score 0.0. No terms means 1.0.
    This is a smoke test, not a quality judgment: your rubric scores replace it."""
    # TODO: implement (README step for auto_score)
    raise NotImplementedError


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile: sort, take the value at rank ceil(p/100 * n) (1-based,
    at least 1). Return None for an empty list."""
    # TODO: implement (README step for percentile)
    raise NotImplementedError


def summarize(results: list[Result], scores: dict[tuple[str, str], float]) -> dict[str, dict[str, Any]]:
    """Group results by model and return {model: stats}. stats keys:
        provider, n, errors,
        mean_score          mean of scores[(prompt_id, model)] over ALL results (missing = 0)
        total_cost_usd, cost_per_task_usd (total / n)
        p50_latency_s, p95_latency_s   over successful results only (None if none)
        mean_output_tokens  over successful results (0.0 if none)
    """
    # TODO: implement (README step for summarize)
    raise NotImplementedError


def pick_winner(summary: dict[str, dict[str, Any]], quality_bar: float) -> str | None:
    """Among models with mean_score >= quality_bar AND zero errors, return the one with the
    lowest cost_per_task_usd, breaking ties by lower p95 latency. None if no model qualifies."""
    # TODO: implement (README step for pick_winner)
    raise NotImplementedError


CSV_COLUMNS = [
    "prompt_id", "provider", "model", "auto_score", "human_score", "latency_s", "input_tokens",
    "output_tokens", "cost_usd", "stop_reason", "error", "output",
]


def write_csv(results: list[Result], scores: dict[tuple[str, str], float], path: pathlib.Path) -> None:
    """Write one row per result, sorted by (prompt_id, model), with columns CSV_COLUMNS.
    auto_score comes from scores (rounded to 3 places); human_score is left blank for you
    to fill in; latency_s rounded to 3 places; cost_usd formatted with 6 decimals."""
    # TODO: implement (README step for write_csv)
    raise NotImplementedError


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
