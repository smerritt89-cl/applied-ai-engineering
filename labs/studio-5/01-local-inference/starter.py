"""Lab 01 (Studio 5): local inference benchmark.

Run a small open model through Ollama's HTTP API or MLX, measure time to first token
(TTFT) and decode speed, and compare one extraction prompt against a Claude model.
Every live part is optional and skips gracefully. Fill in every function marked TODO
(sections 1 and 2); the live adapters and CLI are written for you. Then run:
    pytest studio-5/01-local-inference -q
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import pathlib
import platform
import re
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

HERE = pathlib.Path(__file__).parent
TICKET = (HERE / "fixtures" / "ticket.txt").read_text()

# What a careful person extracts from fixtures/ticket.txt.
EXPECTED = {
    "customer_name": "Dana Okafor",
    "order_id": "A-20931",
    "product": "standing desk frame",
    "issue": "damaged",
    "refund_requested": True,
}

# One JSON Schema, sent to Ollama's `format` field and to Claude's structured outputs.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_name": {"type": "string"},
        "order_id": {"type": "string"},
        "product": {"type": "string"},
        "issue": {"type": "string", "enum": ["damaged", "late", "wrong_item", "billing", "other"]},
        "refund_requested": {"type": "boolean"},
    },
    "required": ["customer_name", "order_id", "product", "issue", "refund_requested"],
    "additionalProperties": False,
}


def build_prompt(ticket: str) -> str:
    return (
        "Extract these fields from the support ticket and reply with one JSON object only: "
        "customer_name, order_id, product (lowercase, as written), issue (one of damaged, late, "
        "wrong_item, billing, other), refund_requested (true only if the customer asks for money back).\n\n"
        f"<ticket>\n{ticket}\n</ticket>"
    )


# ---------------------------------------------------------------- 1. benchmarking math (your TODOs)


def ns_to_s(ns: int | float) -> float:
    """Ollama reports durations in nanoseconds."""
    # TODO: implement (README step 1)
    raise NotImplementedError


def tokens_per_second(tokens: int, seconds: float) -> float:
    """Tokens divided by seconds. Raise ValueError if seconds is not positive."""
    # TODO: implement (README step 1)
    raise NotImplementedError


@dataclass
class Timing:
    load_s: float
    prefill_tokens: int
    prefill_s: float
    prefill_tps: float | None
    decode_tokens: int
    decode_s: float
    decode_tps: float | None
    total_s: float


def parse_ollama_final(chunk: dict) -> Timing:
    """Turn the final (done: true) Ollama chunk into a Timing.

    Missing count or duration fields count as 0. A rate is None when its duration is 0
    (for example, a fully cached prompt has no prefill time).
    """
    # TODO: implement (README step 2)
    raise NotImplementedError


@dataclass
class StreamResult:
    text: str
    ttft_s: float | None
    final: dict = field(default_factory=dict)


def consume_ollama_stream(events: Iterable[tuple[float, str]]) -> StreamResult:
    """Read (seconds_since_request_start, raw_line) pairs from an Ollama /api/chat stream.

    - Skip blank lines.
    - If a chunk has an "error" key, raise RuntimeError with its message.
    - TTFT is the arrival time of the first chunk whose message content is non-empty
      (thinking-only and empty chunks don't count).
    - Concatenate message content into the text.
    - The chunk with done: true is the final chunk. If none arrives, raise ValueError.
    """
    # TODO: implement (README step 3)
    raise NotImplementedError


def summarize(values: list[float], discard_first: int = 0) -> dict:
    """Median, p90 (nearest rank), min, and max after dropping warm-up runs.

    p90 by nearest rank is sorted_values[ceil(0.9 * n) - 1]. Raise ValueError if
    nothing is left after discarding.
    """
    # TODO: implement (README step 4)
    raise NotImplementedError


def bandwidth_ceiling_tps(weights_gb: float, bandwidth_gb_s: float) -> float:
    """Upper bound on single-stream decode speed: every weight is read once per token."""
    # TODO: implement (README step 1)
    raise NotImplementedError


# ---------------------------------------------------------------- 2. response parsing and scoring (your TODOs)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _first_object(text: str) -> str | None:
    """Return the first balanced {...} span, ignoring braces inside JSON strings."""
    start = text.find("{")
    while start != -1:
        depth, in_str, escaped = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        start = text.find("{", start + 1)
    return None


def extract_json(text: str) -> dict:
    """Parse one JSON object from a model reply.

    Try, in order: the whole text; the contents of the first ``` fence; the first balanced
    {...} span. Return a dict. Raise ValueError if no JSON object can be parsed.
    _FENCE and _first_object above are provided helpers.
    """
    # TODO: implement (README step 5)
    raise NotImplementedError


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    return value


def score_fields(predicted: dict, expected: dict) -> dict:
    """Field-level exact match. Strings are compared after collapsing whitespace and casefolding;
    other values (booleans, numbers) must be equal. A missing field is wrong.
    Return {"per_field": {name: bool}, "accuracy": fraction correct}.
    _norm above is a provided helper; also require type(predicted) is type(expected) so 1 != True.
    """
    # TODO: implement (README step 6)
    raise NotImplementedError


# ---------------------------------------------------------------- 3. live adapters (written for you)

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_HOST_URL", "http://localhost:11434")
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"
DEFAULT_MLX_MODEL = "mlx-community/Llama-3.2-3B-Instruct-4bit"
DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"


def ollama_is_running(base_url: str = DEFAULT_OLLAMA_URL, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def ollama_has_model(model: str, base_url: str = DEFAULT_OLLAMA_URL) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=2.0) as resp:
            names = {m.get("name") for m in json.load(resp).get("models", [])}
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return model in names or f"{model}:latest" in names


def stream_ollama_chat(
    prompt: str,
    model: str = DEFAULT_OLLAMA_MODEL,
    base_url: str = DEFAULT_OLLAMA_URL,
    schema: dict | None = SCHEMA,
    num_ctx: int = 8192,
    clock: Callable[[], float] = time.perf_counter,
) -> list[tuple[float, str]]:
    """POST to /api/chat with streaming on and record (arrival_time, line) for every line.
    The timer starts before the request is sent, so TTFT includes queueing and model load."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "options": {"num_ctx": num_ctx, "temperature": 0},
    }
    if schema is not None:
        body["format"] = schema
    req = urllib.request.Request(
        f"{base_url}/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    events: list[tuple[float, str]] = []
    start = clock()
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw in resp:
            events.append((clock() - start, raw.decode("utf-8")))
    return events


def run_ollama(prompt: str, model: str = DEFAULT_OLLAMA_MODEL, base_url: str = DEFAULT_OLLAMA_URL) -> dict:
    result = consume_ollama_stream(stream_ollama_chat(prompt, model=model, base_url=base_url))
    timing = parse_ollama_final(result.final)
    return {"text": result.text, "ttft_s": result.ttft_s, "decode_tps": timing.decode_tps,
            "prefill_tps": timing.prefill_tps, "load_s": timing.load_s, "total_s": timing.total_s}


def mlx_available() -> bool:
    return (
        platform.system() == "Darwin"
        and platform.machine() == "arm64"
        and importlib.util.find_spec("mlx_lm") is not None
    )


_MLX_CACHE: dict[str, Any] = {}


def run_mlx(prompt: str, model: str = DEFAULT_MLX_MODEL, max_tokens: int = 200) -> dict:
    """mlx-lm's stream_generate yields responses with prompt_tps, generation_tps, and peak_memory (GB).
    MLX has no schema-constrained decoding here, so the reply is parsed with extract_json."""
    from mlx_lm import load, stream_generate

    load_s = 0.0
    if model not in _MLX_CACHE:
        t0 = time.perf_counter()
        _MLX_CACHE[model] = load(model)
        load_s = time.perf_counter() - t0
    mlx_model, tokenizer = _MLX_CACHE[model]
    chat_prompt = tokenizer.apply_chat_template([{"role": "user", "content": prompt}], add_generation_prompt=True)
    parts: list[str] = []
    ttft = None
    last = None
    start = time.perf_counter()
    for response in stream_generate(mlx_model, tokenizer, chat_prompt, max_tokens=max_tokens):
        if ttft is None and response.text:
            ttft = time.perf_counter() - start
        parts.append(response.text)
        last = response
    return {"text": "".join(parts), "ttft_s": ttft, "load_s": load_s,
            "prefill_tps": getattr(last, "prompt_tps", None), "decode_tps": getattr(last, "generation_tps", None),
            "peak_memory_gb": getattr(last, "peak_memory", None), "total_s": time.perf_counter() - start}


def run_claude(client: Any, prompt: str, model: str = DEFAULT_CLAUDE_MODEL) -> dict:
    """Stream one structured-output request and time the first visible text.

    Claude Opus 5.5 always thinks before answering, so TTFT here includes thinking time, and
    usage.output_tokens counts thinking tokens too. Effort is set to low for a simple extraction.
    """
    parts: list[str] = []
    ttft = None
    start = time.perf_counter()
    with client.messages.stream(
        model=model,
        max_tokens=4000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            if ttft is None and text:
                ttft = time.perf_counter() - start
            parts.append(text)
        final = stream.get_final_message()
    if final.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"Claude stopped early: {final.stop_reason}")
    return {"text": "".join(parts), "ttft_s": ttft, "total_s": time.perf_counter() - start,
            "input_tokens": final.usage.input_tokens, "output_tokens": final.usage.output_tokens}


# ---------------------------------------------------------------- 4. CLI


def _fmt(x: float | None, unit: str = "") -> str:
    return "n/a" if x is None else f"{x:.2f}{unit}"


def benchmark(runner: Callable[[str], dict], label: str, runs: int) -> None:
    prompt = build_prompt(TICKET)
    results = [runner(prompt) for _ in range(runs)]
    ttfts = [r["ttft_s"] for r in results if r["ttft_s"] is not None]
    decode = [r["decode_tps"] for r in results if r.get("decode_tps")]
    totals = [r["total_s"] for r in results]
    discard = 1 if runs > 1 else 0
    print(f"\n== {label} ({runs} runs, first discarded as warm-up)" if discard else f"\n== {label} (1 run)")
    if results[0].get("load_s"):
        print(f"cold-start load: {_fmt(results[0]['load_s'], ' s')}")
    if len(ttfts) > discard:
        s = summarize(ttfts, discard_first=discard)
        print(f"TTFT median {_fmt(s['median'], ' s')}, p90 {_fmt(s['p90'], ' s')}")
    if len(decode) > discard:
        s = summarize(decode, discard_first=discard)
        print(f"decode median {_fmt(s['median'], ' tok/s')} (tokens from this model's tokenizer)")
    s = summarize(totals, discard_first=discard)
    print(f"seconds per task median {_fmt(s['median'], ' s')}")
    try:
        score = score_fields(extract_json(results[-1]["text"]), EXPECTED)
        print(f"extraction accuracy {score['accuracy']:.0%}: {score['per_field']}")
    except ValueError as err:
        print(f"could not parse the reply as JSON: {err}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", choices=["auto", "ollama", "mlx", "none"], default="auto")
    ap.add_argument("--model", help="Ollama tag or MLX repo (defaults depend on backend)")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--claude", action="store_true", help="also run Claude (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--claude-model", default=DEFAULT_CLAUDE_MODEL)
    args = ap.parse_args()

    backend = args.backend
    if backend == "auto":
        backend = "ollama" if ollama_is_running() else ("mlx" if mlx_available() else "none")
    if backend == "ollama":
        model = args.model or DEFAULT_OLLAMA_MODEL
        if not ollama_has_model(model):
            print(f"Ollama is running but {model} is not pulled. Run: ollama pull {model}")
        else:
            benchmark(lambda p: run_ollama(p, model=model), f"Ollama {model}", args.runs)
    elif backend == "mlx":
        model = args.model or DEFAULT_MLX_MODEL
        benchmark(lambda p: run_mlx(p, model=model), f"MLX {model}", args.runs)
    else:
        print("No local runtime found. Install Ollama (https://ollama.com) or `pip install mlx-lm` on Apple silicon.")

    if args.claude:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Skipping Claude: set ANTHROPIC_API_KEY in labs/.env")
            return
        import anthropic

        client = anthropic.Anthropic()
        benchmark(lambda p: run_claude(client, p, model=args.claude_model), f"Claude {args.claude_model}",
                  max(1, min(args.runs, 3)))


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv(HERE.parent.parent / ".env")
    except ImportError:
        pass
    main()
