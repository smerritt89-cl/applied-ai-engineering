"""Regenerate sample_log.jsonl: a synthetic week of the support_reply workflow (deterministic, no API calls).

    python samples/make_sample_log.py

The numbers are invented but shaped like real traffic: triage on a small model is fast and cheap, the reply on a
large model dominates cost and latency, a few calls fail (overloaded, timeouts), and a few triage calls refuse.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import random
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from solution import PRICES_PER_MTOK, REPLY_MODEL, REPLY_PROMPT_VERSION, TRIAGE_MODEL, TRIAGE_PROMPT_VERSION, cost_usd  # noqa: E402


def main() -> None:
    rng = random.Random(20261111)
    rows = []
    for i in range(60):
        trace_id = hashlib.sha256(f"trace-{i}".encode()).hexdigest()[:32]
        user = "u_" + hashlib.sha256(f"user-{i % 17}".encode()).hexdigest()[:16]
        ts = f"2026-11-{4 + i // 10:02d}T{9 + i % 8:02d}:{(i * 7) % 60:02d}:00+00:00"
        base = dict(schema_version=1, ts=ts, trace_id=trace_id, workflow="support_reply", user=user,
                    input_preview=None, output_preview=None, cache_read_tokens=0, cache_write_tokens=0)
        # triage
        tin, tout = rng.randint(90, 160), rng.randint(2, 4)
        t = dict(base, span_id=f"{2 * i:016x}", step="triage", model=TRIAGE_MODEL, prompt_version=TRIAGE_PROMPT_VERSION)
        if i in (7, 33):
            t.update(status="refused", error_type=None, stop_reason="refusal", latency_ms=round(rng.uniform(250, 500), 1),
                     input_tokens=tin, output_tokens=0)
        elif i in (12, 45):
            t.update(status="error", error_type="OverloadedError", stop_reason=None,
                     latency_ms=round(rng.uniform(40, 120), 1), input_tokens=0, output_tokens=0)
        else:
            t.update(status="ok", error_type=None, stop_reason="end_turn", latency_ms=round(rng.uniform(220, 650), 1),
                     input_tokens=tin, output_tokens=tout)
        t["cost_usd"] = cost_usd(TRIAGE_MODEL, t)
        rows.append(t)
        if t["status"] != "ok":
            continue
        # reply: the system prompt is cached after the first call of each hour
        cached = rng.random() < 0.7
        r = dict(base, span_id=f"{2 * i + 1:016x}", step="reply", model=REPLY_MODEL, prompt_version=REPLY_PROMPT_VERSION)
        rin, rout = rng.randint(150, 400), rng.randint(90, 220)
        r["cache_read_tokens"] = 1800 if cached else 0
        r["cache_write_tokens"] = 0 if cached else 1800
        if rng.random() < 0.06:
            r.update(status="error", error_type="APITimeoutError", stop_reason=None,
                     latency_ms=round(rng.uniform(30000, 31000), 1), input_tokens=0, output_tokens=0,
                     cache_read_tokens=0, cache_write_tokens=0)
        else:
            slow = rng.random() < 0.1
            r.update(status="ok", error_type=None, stop_reason="end_turn", input_tokens=rin, output_tokens=rout,
                     latency_ms=round(rng.uniform(5000, 9000) if slow else rng.uniform(1800, 3800), 1))
        r["cost_usd"] = cost_usd(REPLY_MODEL, r)
        rows.append(r)
    out = HERE / "sample_log.jsonl"
    out.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    print(f"wrote {len(rows)} records to {out}")


if __name__ == "__main__":
    main()
