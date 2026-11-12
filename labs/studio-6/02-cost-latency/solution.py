"""Lab 02 (Studio 6): measure a baseline, add prompt caching, compare. Reference solution.

Pipeline:
    shared document + questions
      -> build_request (baseline: no cache_control; cached: breakpoint after the document)
      -> timed_call (stream, record time to first token, first text, and total; keep usage)
      -> run_comparison (interleave baseline and cached requests on the same questions)
      -> summarize / compare / cache_health (dollars from usage, percentiles from timings)
"""
from __future__ import annotations

import json
import math
import pathlib
import time

MODEL = "claude-haiku-5-5"
MAX_TOKENS = 4000
HERE = pathlib.Path(__file__).parent
SAMPLES_DIR = HERE / "samples"
FIXTURES_DIR = HERE / "fixtures"

# USD per million tokens, from the Claude pricing page on 2026-11-11. Check it before you rely on these.
# Haiku 5.5 rates are for prompts up to 100,000 tokens.
PRICES_CHECKED_ON = "2026-11-11"
PRICES = {
    "claude-opus-5-5": {"input": 4.00, "cache_write_5m": 5.00, "cache_write_1h": 8.00, "cache_read": 0.20, "output": 20.00},
    "claude-sonnet-5-5": {"input": 2.00, "cache_write_5m": 2.50, "cache_write_1h": 4.00, "cache_read": 0.10, "output": 10.00},
    "claude-haiku-5-5": {"input": 0.10, "cache_write_5m": 0.125, "cache_write_1h": 0.20, "cache_read": 0.01, "output": 0.50},
}

INSTRUCTIONS = """You answer customer questions for Northwind Field Services support agents.
Answer only from the handbook provided. Give the specific answer first, then the reason, in at most three sentences.
If the handbook doesn't cover the question, say so and recommend escalating to a team lead."""

QUESTIONS = [
    "A Plus customer wants to reschedule tomorrow morning's visit. It's their fourth late change this year. Is there a fee?",
    "A Basic customer has no heat and it's 2 degrees outside. Can they get an emergency visit, and what does it cost?",
    "A repair failed again 95 days after the original visit. Is the return visit free?",
    "The technician never showed up and didn't call. What do we owe the customer?",
    "Can a customer who downgraded in March downgrade again in August?",
    "A customer's payment failed twice in a row. What happens to their Premier plan?",
]


# ---------------------------------------------------------------- 1. dollars


def request_cost(usage: dict, model: str, prices: dict = PRICES) -> float:
    """Dollar cost of one response from its usage meters."""
    p = prices[model]
    writes = usage.get("cache_creation_input_tokens", 0) or 0
    breakdown = usage.get("cache_creation") or {}
    w1h = breakdown.get("ephemeral_1h_input_tokens", 0) or 0
    w5m = writes - w1h
    total = (
        (usage.get("input_tokens", 0) or 0) * p["input"]
        + w5m * p["cache_write_5m"]
        + w1h * p["cache_write_1h"]
        + (usage.get("cache_read_input_tokens", 0) or 0) * p["cache_read"]
        + (usage.get("output_tokens", 0) or 0) * p["output"]
    )
    return total / 1_000_000


def total_input(usage: dict) -> int:
    """Prompt size: the three input meters added together."""
    return (
        (usage.get("input_tokens", 0) or 0)
        + (usage.get("cache_creation_input_tokens", 0) or 0)
        + (usage.get("cache_read_input_tokens", 0) or 0)
    )


# ---------------------------------------------------------------- 2. percentiles


def percentile(values, p: float) -> float:
    """Nearest-rank percentile."""
    if not values:
        raise ValueError("no samples")
    s = sorted(values)
    k = math.ceil(p / 100 * len(s))
    return s[max(k, 1) - 1]


# ---------------------------------------------------------------- 3. requests


def build_request(document: str, question: str, *, cached: bool, model: str = MODEL) -> dict:
    """Keyword arguments for client.messages.stream()."""
    doc_block = {"type": "text", "text": f"<handbook>\n{document}\n</handbook>"}
    if cached:
        doc_block["cache_control"] = {"type": "ephemeral"}
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "output_config": {"effort": "low"},
        "system": [{"type": "text", "text": INSTRUCTIONS}, doc_block],
        "messages": [{"role": "user", "content": question}],
    }


def usage_to_dict(usage) -> dict:
    """Normalize an SDK usage object (or a dict) into plain numbers."""
    get = (lambda k: usage.get(k)) if isinstance(usage, dict) else (lambda k: getattr(usage, k, None))
    out = {
        "input_tokens": get("input_tokens") or 0,
        "cache_creation_input_tokens": get("cache_creation_input_tokens") or 0,
        "cache_read_input_tokens": get("cache_read_input_tokens") or 0,
        "output_tokens": get("output_tokens") or 0,
    }
    breakdown = get("cache_creation")
    if breakdown is not None:
        bget = (lambda k: breakdown.get(k)) if isinstance(breakdown, dict) else (lambda k: getattr(breakdown, k, None))
        out["cache_creation"] = {
            "ephemeral_5m_input_tokens": bget("ephemeral_5m_input_tokens") or 0,
            "ephemeral_1h_input_tokens": bget("ephemeral_1h_input_tokens") or 0,
        }
    return out


def timed_call(client, params: dict, clock=time.perf_counter) -> dict:
    """Stream one request and record when things happened (seconds after sending)."""
    sent = clock()
    ttft = first_text = None
    with client.messages.stream(**params) as stream:
        for event in stream:
            now = clock() - sent
            if event.type == "message_start" and ttft is None:
                ttft = now
            elif (
                event.type == "content_block_delta"
                and getattr(event.delta, "type", None) == "text_delta"
                and first_text is None
            ):
                first_text = now
        message = stream.get_final_message()
    total = clock() - sent
    return {
        "model": params["model"],
        "ttft_s": ttft,
        "first_text_s": first_text,
        "total_s": total,
        "stop_reason": message.stop_reason,
        "usage": usage_to_dict(message.usage),
    }


def run_comparison(client, document: str, questions: list[str], *, rounds: int = 1, clock=time.perf_counter) -> list[dict]:
    """Interleave the two arms on the same questions: baseline then cached, cached then baseline, and so on."""
    records = []
    order = 0
    for r in range(rounds):
        for i, q in enumerate(questions):
            arms = ("baseline", "cached") if order % 2 == 0 else ("cached", "baseline")
            order += 1
            for arm in arms:
                rec = timed_call(client, build_request(document, q, cached=(arm == "cached")), clock=clock)
                rec.update({"arm": arm, "question_index": i, "round": r})
                records.append(rec)
    return records


# ---------------------------------------------------------------- 4. analysis


def summarize(records: list[dict]) -> dict:
    """Cost and latency summary for one arm."""
    if not records:
        raise ValueError("no records")
    costs = [request_cost(r["usage"], r["model"]) for r in records]
    reads = sum(r["usage"].get("cache_read_input_tokens", 0) for r in records)
    inputs = sum(total_input(r["usage"]) for r in records)

    def pcts(key):
        vals = [r[key] for r in records if r.get(key) is not None]
        return {"p50": percentile(vals, 50), "p95": percentile(vals, 95)} if vals else {"p50": None, "p95": None}

    return {
        "n": len(records),
        "total_cost": sum(costs),
        "mean_cost": sum(costs) / len(costs),
        "cache_read_fraction": reads / inputs if inputs else 0.0,
        "ttft_s": pcts("ttft_s"),
        "first_text_s": pcts("first_text_s"),
        "total_s": pcts("total_s"),
    }


def compare(records: list[dict]) -> dict:
    """Summaries per arm and the cached/baseline ratios that matter."""
    base = summarize([r for r in records if r["arm"] == "baseline"])
    cached = summarize([r for r in records if r["arm"] == "cached"])

    def ratio(a, b):
        return a / b if a is not None and b else None

    return {
        "baseline": base,
        "cached": cached,
        "cost_ratio": ratio(cached["mean_cost"], base["mean_cost"]),
        "ttft_p50_ratio": ratio(cached["ttft_s"]["p50"], base["ttft_s"]["p50"]),
        "total_p50_ratio": ratio(cached["total_s"]["p50"], base["total_s"]["p50"]),
    }


def cache_health(records: list[dict], min_prefix: int = 512) -> list[str]:
    """Warnings about a cached arm, in time order. Empty list means healthy."""
    warnings = []
    if not records:
        return ["no records"]
    if total_input(records[0]["usage"]) < min_prefix:
        warnings.append(f"prompt is under {min_prefix} tokens, below the minimum cacheable length")
    warm = records[1:]
    if warm and all(r["usage"].get("cache_read_input_tokens", 0) == 0 for r in warm):
        warnings.append("no cache reads after the first request: look for a silent invalidator")
    rewritten = [
        r for r in warm
        if total_input(r["usage"]) and r["usage"].get("cache_creation_input_tokens", 0) / total_input(r["usage"]) >= 0.5
    ]
    if warm and len(rewritten) > len(warm) / 2:
        warnings.append("most warm requests rewrite the cache: the prefix is changing between requests")
    return warnings


def load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES_DIR / name).read_text())


def format_report(result: dict) -> str:
    lines = []
    for arm in ("baseline", "cached"):
        s = result[arm]
        lines.append(
            f"{arm:9s} n={s['n']:2d}  mean ${s['mean_cost']:.6f}  read {s['cache_read_fraction']:.0%}  "
            f"TTFT p50 {s['ttft_s']['p50']:.2f}s  first text p50 {s['first_text_s']['p50'] or 0:.2f}s  "
            f"total p50 {s['total_s']['p50']:.2f}s"
        )
    lines.append(
        f"cached/baseline: cost x{result['cost_ratio']:.2f}, TTFT p50 x{result['ttft_p50_ratio']:.2f}, "
        f"total p50 x{result['total_p50_ratio']:.2f}"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    import anthropic

    client = anthropic.Anthropic()
    document = (SAMPLES_DIR / "handbook.md").read_text()
    records = run_comparison(client, document, QUESTIONS)
    print(format_report(compare(records)))
    for w in cache_health([r for r in records if r["arm"] == "cached"]):
        print("WARNING:", w)
