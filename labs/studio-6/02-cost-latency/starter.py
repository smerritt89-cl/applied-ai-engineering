"""Lab 02 (Studio 6): measure a baseline, add prompt caching, compare (your file: fill in the TODOs).

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
    """Dollar cost of one response from its usage meters.

    usage has input_tokens, cache_creation_input_tokens, cache_read_input_tokens,
    output_tokens, and optionally cache_creation = {"ephemeral_5m_input_tokens": ...,
    "ephemeral_1h_input_tokens": ...}. Price 1h writes at the 1h rate when the
    breakdown is present; treat all other writes as 5-minute writes. Missing or
    None meters count as 0. Raise KeyError for a model not in prices.
    """
    # TODO
    raise NotImplementedError


def total_input(usage: dict) -> int:
    """Prompt size: the three input meters added together (None counts as 0)."""
    # TODO
    raise NotImplementedError


# ---------------------------------------------------------------- 2. percentiles


def percentile(values, p: float) -> float:
    """Nearest-rank percentile: the smallest value such that at least p percent of
    values are less than or equal to it. Raise ValueError on an empty sequence."""
    # TODO
    raise NotImplementedError


# ---------------------------------------------------------------- 3. requests


def build_request(document: str, question: str, *, cached: bool, model: str = MODEL) -> dict:
    """Keyword arguments for client.messages.stream().

    Return a dict with exactly these keys: model, max_tokens (MAX_TOKENS),
    output_config ({"effort": "low"}), system, messages.
      system   = two text blocks: INSTRUCTIONS, then the document wrapped as
                 "<handbook>\n{document}\n</handbook>".
                 When cached is True, the SECOND block (the document) gets
                 "cache_control": {"type": "ephemeral"}. When False, no block has it.
      messages = one user message whose content is the question (after the breakpoint).
    Do not add temperature, top_p, or top_k (the current API rejects them), and
    don't put anything that varies per request (dates, ids) in system.
    """
    # TODO
    raise NotImplementedError


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
    """Stream one request and record when things happened (seconds after sending).

    Call clock() once before opening the stream. While iterating the stream's events:
      ttft_s        = time of the first event whose type is "message_start"
      first_text_s  = time of the first "content_block_delta" whose delta.type is "text_delta"
                      (None if the response had no text)
    After the loop, read stream.get_final_message(), then total_s = clock() - sent.
    Return {"model", "ttft_s", "first_text_s", "total_s", "stop_reason",
            "usage": usage_to_dict(message.usage)}.
    """
    # TODO
    raise NotImplementedError


def run_comparison(client, document: str, questions: list[str], *, rounds: int = 1, clock=time.perf_counter) -> list[dict]:
    """Interleave the two arms on the same questions so both see the same service conditions.

    For each round, for each question i: on even-numbered pairs (counting across
    rounds, starting at 0) run baseline then cached; on odd-numbered pairs run
    cached then baseline. Each record is timed_call(...) plus
    {"arm": "baseline" or "cached", "question_index": i, "round": r}.
    Return records in the order the requests were sent.
    """
    # TODO
    raise NotImplementedError


# ---------------------------------------------------------------- 4. analysis


def summarize(records: list[dict]) -> dict:
    """Cost and latency summary for one arm.

    Return {"n", "total_cost", "mean_cost", "cache_read_fraction",
            "ttft_s": {"p50", "p95"}, "first_text_s": {"p50", "p95"}, "total_s": {"p50", "p95"}}.
    cache_read_fraction = sum of cache_read_input_tokens / sum of total_input over records.
    Percentiles skip None values; if every value is None, report None for both.
    Raise ValueError on an empty list.
    """
    # TODO
    raise NotImplementedError


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
    """Warnings about a cached arm (records in time order). Empty list means healthy.

    Return these strings, in this order, when they apply:
      f"prompt is under {min_prefix} tokens, below the minimum cacheable length"
          if the first record's total input is below min_prefix
      "no cache reads after the first request: look for a silent invalidator"
          if there are records after the first and none of them read from cache
      "most warm requests rewrite the cache: the prefix is changing between requests"
          if more than half of the records after the first have cache writes making up
          at least half of their total input
    An empty records list returns ["no records"].
    """
    # TODO
    raise NotImplementedError


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
