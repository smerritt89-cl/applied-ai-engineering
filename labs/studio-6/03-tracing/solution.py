"""Lab 03 (Studio 6): trace, log, and chart a two-step LLM workflow (reference solution).

Workflow (a support desk):
    ticket -> step 1 "triage"  (claude-haiku-5-5, prompt triage-v3): pick a category
           -> step 2 "reply"   (claude-opus-5-5,  prompt reply-v7):  draft a reply
Each step runs inside an OpenTelemetry span that follows the GenAI semantic conventions, and writes one
structured JSONL record with redacted content. `aggregate` and `render_markdown` turn the log into a small
cost and latency dashboard.

    python solution.py dashboard samples/sample_log.jsonl --out dashboard.md
    python solution.py run            # live: calls Claude on samples/tickets.jsonl (needs ANTHROPIC_API_KEY)
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import json
import math
import pathlib
import re
import secrets
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

HERE = pathlib.Path(__file__).parent
SCHEMA_VERSION = 1
WORKFLOW = "support_reply"

TRIAGE_MODEL = "claude-haiku-5-5"
TRIAGE_PROMPT_VERSION = "triage-v3"
REPLY_MODEL = "claude-opus-5-5"
REPLY_PROMPT_VERSION = "reply-v7"
CATEGORIES = ("billing", "bug", "account", "other")

# USD per million tokens, from https://platform.claude.com/docs/en/about-claude/pricing (checked 2026-11-11).
# Haiku 5.5 prices are for prompts up to 100,000 tokens. Prices change: version this table with your code.
PRICES_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.00, "cache_write_5m": 5.00, "cache_read": 0.20, "output": 20.00},
    "claude-haiku-5-5": {"input": 0.10, "cache_write_5m": 0.125, "cache_read": 0.01, "output": 0.50},
}

TRIAGE_SYSTEM = (
    "You triage customer support tickets. Reply with exactly one word, the category: "
    "billing, bug, account, or other."
)
REPLY_SYSTEM = (
    "You draft short, polite replies to customer support tickets for a human agent to review. "
    "Do not promise refunds or dates. Keep it under 120 words."
)

# ----------------------------------------------------------------- tracing (no SDK required)

try:  # opentelemetry-api is enough: without an SDK, spans are no-ops with invalid ids.
    from opentelemetry import trace as _otel_trace
    from opentelemetry.trace import Status, StatusCode
except ImportError:  # pragma: no cover - exercised only when the API is missing
    _otel_trace = None


class _NoopSpanContext:
    is_valid = False
    trace_id = 0
    span_id = 0


class _NoopSpan:
    def set_attribute(self, key, value):
        pass

    def set_status(self, *args, **kwargs):
        pass

    def record_exception(self, exc):
        pass

    def get_span_context(self):
        return _NoopSpanContext()


class _NoopTracer:
    @contextlib.contextmanager
    def start_as_current_span(self, name, **kwargs):
        yield _NoopSpan()


def get_tracer(name: str = "aae.lab.tracing"):
    """The global OpenTelemetry tracer if the API is installed, else a no-op stand-in."""
    if _otel_trace is None:
        return _NoopTracer()
    return _otel_trace.get_tracer(name)


def _mark_error(span, exc: BaseException) -> None:
    span.record_exception(exc)
    if _otel_trace is not None:
        span.set_status(Status(StatusCode.ERROR, type(exc).__name__))


def _ids(span, fallback_trace: str | None = None) -> tuple[str, str]:
    ctx = span.get_span_context()
    if ctx.is_valid:
        return f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}"
    return fallback_trace or secrets.token_hex(16), secrets.token_hex(8)


# ----------------------------------------------------------------- 1. redaction

SECRET_PATTERNS = [
    # Keys with an sk- prefix (Anthropic's documented admin keys, for example, start sk-ant-admin).
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    # Authorization headers.
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
]
# key=value or key: value where the key name says "secret". Keeps the key name so the log stays readable.
SECRET_KV = re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b(\s*[:=]\s*)([^\s,;]+)")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
PHONE_PATTERNS = [
    # E.164, such as +442079460958
    re.compile(r"(?<![\w+])\+\d{8,15}\b"),
    # North American style: (415) 555-0134, 415-555-0134, 415.555.0134, +1 415 555 0134
    re.compile(r"(?<![\w+])(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?![\w])"),
]


def redact(text: str) -> str:
    """Replace secrets with [SECRET], email addresses with [EMAIL], phone numbers with [PHONE].

    Order matters: secrets first (a key can contain digit runs that look like phone numbers), then emails,
    then phones. For key=value secrets keep the key and separator: "api_key=abc123" -> "api_key=[SECRET]".
    Idempotent: redact(redact(x)) == redact(x).
    """
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[SECRET]", text)
    text = SECRET_KV.sub(lambda m: m.group(1) + m.group(2) + "[SECRET]" if m.group(3) != "[SECRET]" else m.group(0), text)
    text = EMAIL.sub("[EMAIL]", text)
    for pattern in PHONE_PATTERNS:
        text = pattern.sub("[PHONE]", text)
    return text


def redact_value(value: Any) -> Any:
    """Apply `redact` to every string inside nested dicts, lists, and tuples. Leave other types alone.
    Dict keys are not redacted. Return a new structure; don't mutate the input."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redact_value(v) for v in value)
    return value


def pseudonymize(user_id: str, key: bytes) -> str:
    """Stable pseudonym for a user: "u_" + the first 16 hex characters of HMAC-SHA256(key, user_id).
    A keyed hash (not a bare hash) so someone without the key can't rebuild the mapping from a list of emails."""
    digest = hmac.new(key, user_id.encode("utf-8"), hashlib.sha256).hexdigest()
    return "u_" + digest[:16]


# ----------------------------------------------------------------- 2. cost

def cost_usd(model: str, usage: dict[str, int]) -> float:
    """Dollar cost of one call. `usage` has input_tokens (uncached), output_tokens, cache_read_tokens,
    cache_write_tokens (5-minute cache). Raise ValueError for a model missing from PRICES_PER_MTOK:
    a silent zero would make the dashboard lie."""
    if model not in PRICES_PER_MTOK:
        raise ValueError(f"no price for model {model!r}; add it to PRICES_PER_MTOK")
    p = PRICES_PER_MTOK[model]
    total = (
        usage.get("input_tokens", 0) * p["input"]
        + usage.get("cache_write_tokens", 0) * p["cache_write_5m"]
        + usage.get("cache_read_tokens", 0) * p["cache_read"]
        + usage.get("output_tokens", 0) * p["output"]
    )
    return total / 1_000_000


# ----------------------------------------------------------------- 3. records

RECORD_FIELDS: dict[str, tuple[type, ...]] = {
    "schema_version": (int,),
    "ts": (str,),
    "trace_id": (str,),
    "span_id": (str,),
    "workflow": (str,),
    "step": (str,),
    "model": (str,),
    "prompt_version": (str,),
    "status": (str,),  # ok | error | refused | truncated
    "error_type": (str, type(None)),
    "stop_reason": (str, type(None)),
    "latency_ms": (int, float),
    "input_tokens": (int,),
    "output_tokens": (int,),
    "cache_read_tokens": (int,),
    "cache_write_tokens": (int,),
    "cost_usd": (int, float),
    "user": (str,),
    "input_preview": (str, type(None)),
    "output_preview": (str, type(None)),
}
STATUSES = {"ok", "error", "refused", "truncated"}


def validate_record(record: dict[str, Any]) -> list[str]:
    """Return a list of problems (empty means valid):
      "missing field: X"           for each field of RECORD_FIELDS not present
      "unexpected field: X"        for each extra field
      "bad type: X"                when a value's type is not allowed (bool is not an int here)
      "bad status: X"              when status is not in STATUSES
      "negative: X"                for negative latency_ms, token counts, or cost_usd
      "unredacted: X"              when input_preview or output_preview changes under redact()
      "error without error_type"   when status == "error" and error_type is None
    """
    problems: list[str] = []
    for name, types in RECORD_FIELDS.items():
        if name not in record:
            problems.append(f"missing field: {name}")
            continue
        value = record[name]
        if isinstance(value, bool) or not isinstance(value, types):
            problems.append(f"bad type: {name}")
    for name in record:
        if name not in RECORD_FIELDS:
            problems.append(f"unexpected field: {name}")
    if record.get("status") not in STATUSES and "status" in record:
        problems.append(f"bad status: {record['status']}")
    for name in ("latency_ms", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cost_usd"):
        value = record.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value < 0:
            problems.append(f"negative: {name}")
    for name in ("input_preview", "output_preview"):
        value = record.get(name)
        if isinstance(value, str) and redact(value) != value:
            problems.append(f"unredacted: {name}")
    if record.get("status") == "error" and record.get("error_type") is None:
        problems.append("error without error_type")
    return problems


def _usage(response) -> dict[str, int]:
    u = getattr(response, "usage", None)
    return {
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "cache_read_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_write_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }


def _text(response) -> str:
    return "".join(b.text for b in getattr(response, "content", []) if getattr(b, "type", None) == "text")


def _status(stop_reason: str | None) -> str:
    if stop_reason == "refusal":
        return "refused"
    if stop_reason == "max_tokens":
        return "truncated"
    return "ok"


def _preview(text: str | None, capture: bool, limit: int = 200) -> str | None:
    if not capture or text is None:
        return None
    # Redact BEFORE truncating, so a cut can't split an email into something the pattern no longer matches.
    return redact(text)[:limit]


class ListLog:
    """In-memory log, for tests."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def write(self, record: dict[str, Any]) -> None:
        self.records.append(record)


class JsonlLog:
    """Append one JSON object per line."""

    def __init__(self, path: str | pathlib.Path) -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")


def read_jsonl(path: str | pathlib.Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in pathlib.Path(path).read_text().splitlines() if line.strip()]


# ----------------------------------------------------------------- 4. the workflow

def call_step(
    client,
    *,
    tracer,
    log,
    step: str,
    model: str,
    prompt_version: str,
    system: str,
    user_text: str,
    max_tokens: int,
    trace_id: str,
    user: str,
    capture_content: bool,
    clock: Callable[[], float],
):
    """Run one model call inside a span named "chat {model}", set GenAI attributes, write one record.

    Span attributes (GenAI semantic conventions, status Development):
      gen_ai.operation.name = "chat", gen_ai.provider.name = "anthropic", gen_ai.request.model,
      gen_ai.prompt.name = step, gen_ai.prompt.version, and after the call gen_ai.response.model,
      gen_ai.response.finish_reasons = [stop_reason], gen_ai.usage.output_tokens, and
      gen_ai.usage.input_tokens = input + cache read + cache write (the convention counts cached tokens as input;
      Claude's usage.input_tokens does not). Also app.cost_usd. Never put prompt text on the span.
    On an exception: record it on the span, set ERROR status and error.type, write a record with status "error",
    zero tokens and cost, then re-raise.
    Returns (response_text, record).
    """
    with tracer.start_as_current_span(f"chat {model}") as span:
        _, span_id = _ids(span, trace_id)
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.provider.name", "anthropic")
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.request.max_tokens", max_tokens)
        span.set_attribute("gen_ai.prompt.name", step)
        span.set_attribute("gen_ai.prompt.version", prompt_version)
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "ts": datetime.now(timezone.utc).isoformat(),
            "trace_id": trace_id,
            "span_id": span_id,
            "workflow": WORKFLOW,
            "step": step,
            "model": model,
            "prompt_version": prompt_version,
            "user": user,
            "input_preview": _preview(user_text, capture_content),
        }
        start = clock()
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_text}],
            )
        except Exception as exc:
            record.update(
                status="error", error_type=type(exc).__name__, stop_reason=None,
                latency_ms=round((clock() - start) * 1000, 3), input_tokens=0, output_tokens=0,
                cache_read_tokens=0, cache_write_tokens=0, cost_usd=0.0, output_preview=None,
            )
            span.set_attribute("error.type", type(exc).__name__)
            _mark_error(span, exc)
            log.write(record)
            raise
        latency_ms = round((clock() - start) * 1000, 3)
        usage = _usage(response)
        text = _text(response)
        stop_reason = getattr(response, "stop_reason", None)
        cost = cost_usd(model, usage)
        span.set_attribute("gen_ai.response.model", getattr(response, "model", model) or model)
        if stop_reason:
            span.set_attribute("gen_ai.response.finish_reasons", [stop_reason])
        span.set_attribute(
            "gen_ai.usage.input_tokens",
            usage["input_tokens"] + usage["cache_read_tokens"] + usage["cache_write_tokens"],
        )
        span.set_attribute("gen_ai.usage.output_tokens", usage["output_tokens"])
        span.set_attribute("gen_ai.usage.cache_read.input_tokens", usage["cache_read_tokens"])
        span.set_attribute("gen_ai.usage.cache_write.input_tokens", usage["cache_write_tokens"])
        span.set_attribute("app.cost_usd", cost)
        record.update(
            status=_status(stop_reason), error_type=None, stop_reason=stop_reason, latency_ms=latency_ms,
            cost_usd=cost, output_preview=_preview(text, capture_content), **usage,
        )
        log.write(record)
        return text, record


def parse_category(text: str) -> str:
    """First word of the reply, lowercased and stripped of punctuation, if it is a known category; else "other"."""
    words = re.findall(r"[a-z]+", text.lower())
    return words[0] if words and words[0] in CATEGORIES else "other"


def run_workflow(
    client,
    ticket: str,
    *,
    user_id: str,
    log,
    hmac_key: bytes,
    tracer=None,
    capture_content: bool = False,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Triage then reply, under one root span named WORKFLOW.

    Both records share the root span's trace id (or one random 32-hex id when tracing is a no-op).
    If triage does not finish with status "ok", skip the reply and return early.
    Returns {"trace_id", "category", "reply", "status"} where status is the last step's status.
    """
    tracer = tracer or get_tracer()
    user = pseudonymize(user_id, hmac_key)
    with tracer.start_as_current_span(WORKFLOW) as root:
        trace_id, _ = _ids(root)
        root.set_attribute("app.workflow", WORKFLOW)
        root.set_attribute("app.user", user)
        try:
            text, rec = call_step(
                client, tracer=tracer, log=log, step="triage", model=TRIAGE_MODEL,
                prompt_version=TRIAGE_PROMPT_VERSION, system=TRIAGE_SYSTEM, user_text=ticket,
                max_tokens=1024, trace_id=trace_id, user=user, capture_content=capture_content, clock=clock,
            )
            if rec["status"] != "ok":
                return {"trace_id": trace_id, "category": None, "reply": None, "status": rec["status"]}
            category = parse_category(text)
            root.set_attribute("app.category", category)
            reply, rec = call_step(
                client, tracer=tracer, log=log, step="reply", model=REPLY_MODEL,
                prompt_version=REPLY_PROMPT_VERSION, system=REPLY_SYSTEM,
                user_text=f"Category: {category}\n\nTicket:\n{ticket}",
                max_tokens=4096, trace_id=trace_id, user=user, capture_content=capture_content, clock=clock,
            )
        except Exception as exc:
            _mark_error(root, exc)
            raise
        return {"trace_id": trace_id, "category": category, "reply": reply, "status": rec["status"]}


# ----------------------------------------------------------------- 5. aggregation and dashboard

def percentile(values: Iterable[float], p: float) -> float | None:
    """Nearest-rank percentile: sort, take the value at 1-based rank ceil(p/100 * n). p in (0, 100].
    None for an empty input."""
    xs = sorted(values)
    if not xs:
        return None
    if not 0 < p <= 100:
        raise ValueError("p must be in (0, 100]")
    rank = math.ceil(p / 100 * len(xs))
    return xs[rank - 1]


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize a log.

    Returns {
      "rows": [ one dict per (step, model), sorted by step then model, with keys
                step, model, n, error_rate, refusal_rate, p50_ms, p95_ms, input_tokens, output_tokens, cost_usd ],
      "traces": number of distinct trace_id,
      "total_cost_usd": sum of cost_usd,
      "cost_per_trace_usd": total cost / traces (None if no traces),
      "trace_p50_ms", "trace_p95_ms": percentiles of per-trace latency (the sum of its steps' latency_ms),
      "failed_traces": traces with at least one record whose status is not "ok",
    }
    error_rate and refusal_rate are fractions of n (status "error" and status "refused").
    Latency percentiles include failed calls: a slow error is still slow for the user.
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    traces: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        groups.setdefault((r["step"], r["model"]), []).append(r)
        traces.setdefault(r["trace_id"], []).append(r)
    rows = []
    for (step, model), rs in sorted(groups.items()):
        n = len(rs)
        lat = [r["latency_ms"] for r in rs]
        rows.append({
            "step": step,
            "model": model,
            "n": n,
            "error_rate": sum(r["status"] == "error" for r in rs) / n,
            "refusal_rate": sum(r["status"] == "refused" for r in rs) / n,
            "p50_ms": percentile(lat, 50),
            "p95_ms": percentile(lat, 95),
            "input_tokens": sum(r["input_tokens"] + r["cache_read_tokens"] + r["cache_write_tokens"] for r in rs),
            "output_tokens": sum(r["output_tokens"] for r in rs),
            "cost_usd": sum(r["cost_usd"] for r in rs),
        })
    total = sum(r["cost_usd"] for r in records)
    per_trace_latency = [sum(r["latency_ms"] for r in rs) for rs in traces.values()]
    return {
        "rows": rows,
        "traces": len(traces),
        "total_cost_usd": total,
        "cost_per_trace_usd": (total / len(traces)) if traces else None,
        "trace_p50_ms": percentile(per_trace_latency, 50),
        "trace_p95_ms": percentile(per_trace_latency, 95),
        "failed_traces": sum(any(r["status"] != "ok" for r in rs) for rs in traces.values()),
    }


def _fmt_ms(x: float | None) -> str:
    return "n/a" if x is None else f"{x:,.0f} ms"


def render_markdown(agg: dict[str, Any], title: str = "Support reply: cost and latency") -> str:
    """A Markdown dashboard: a headline section, then a table with one row per (step, model).

    Headline lines (exact labels): "Traces: N", "Failed traces: N (P%)", "Total cost: $X.XXXX",
    "Cost per trace: $X.XXXXXX", "Trace latency p50 / p95: A ms / B ms".
    Table columns: Step | Model | Calls | Error rate | Refusal rate | p50 | p95 | Input tokens | Output tokens | Cost.
    Rates as percentages with one decimal; cost with 4 decimals; latency as whole ms with thousands separators.
    """
    traces = agg["traces"]
    failed_pct = (100 * agg["failed_traces"] / traces) if traces else 0.0
    cpt = agg["cost_per_trace_usd"]
    lines = [
        f"# {title}",
        "",
        f"- Traces: {traces}",
        f"- Failed traces: {agg['failed_traces']} ({failed_pct:.1f}%)",
        f"- Total cost: ${agg['total_cost_usd']:.4f}",
        f"- Cost per trace: " + ("n/a" if cpt is None else f"${cpt:.6f}"),
        f"- Trace latency p50 / p95: {_fmt_ms(agg['trace_p50_ms'])} / {_fmt_ms(agg['trace_p95_ms'])}",
        "",
        "| Step | Model | Calls | Error rate | Refusal rate | p50 | p95 | Input tokens | Output tokens | Cost |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in agg["rows"]:
        lines.append(
            f"| {r['step']} | {r['model']} | {r['n']} | {100 * r['error_rate']:.1f}% | {100 * r['refusal_rate']:.1f}% "
            f"| {_fmt_ms(r['p50_ms'])} | {_fmt_ms(r['p95_ms'])} | {r['input_tokens']:,} | {r['output_tokens']:,} "
            f"| ${r['cost_usd']:.4f} |"
        )
    lines += ["", "Percentiles are nearest-rank. Failed calls are included in latency. Costs use PRICES_PER_MTOK."]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------- CLI

def _console_tracer():
    """A tracer that prints spans to stdout, if opentelemetry-sdk is installed; else the default tracer."""
    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
    except ImportError:
        print("opentelemetry-sdk not installed: spans are no-ops (pip install opentelemetry-sdk to see them)")
        return get_tracer()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    return provider.get_tracer("aae.lab.tracing")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dashboard", help="render a Markdown dashboard from a JSONL log")
    d.add_argument("log")
    d.add_argument("--out", default=None)
    r = sub.add_parser("run", help="run the workflow live on samples/tickets.jsonl")
    r.add_argument("--log", default=str(HERE / "logs" / "run.jsonl"))
    r.add_argument("--capture-content", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "dashboard":
        md = render_markdown(aggregate(read_jsonl(args.log)))
        if args.out:
            pathlib.Path(args.out).write_text(md)
            print(f"wrote {args.out}")
        else:
            print(md)
        return 0

    import os

    import anthropic

    client = anthropic.Anthropic()
    key = os.environ.get("LOG_HMAC_KEY", "dev-only-not-secret").encode()
    tracer = _console_tracer()
    log = JsonlLog(args.log)
    for t in read_jsonl(HERE / "samples" / "tickets.jsonl"):
        try:
            out = run_workflow(client, t["text"], user_id=t["user"], log=log, hmac_key=key, tracer=tracer,
                               capture_content=args.capture_content)
            print(out["trace_id"], out["status"], out["category"])
        except anthropic.APIError as exc:
            print("failed:", type(exc).__name__, file=sys.stderr)
    print(f"log: {args.log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
