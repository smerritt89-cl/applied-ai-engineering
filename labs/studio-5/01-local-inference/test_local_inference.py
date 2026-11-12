"""Tests for Studio 5 lab 01. Offline tests need nothing but Python.

- Local tests run only if Ollama is serving on localhost:11434 (or mlx-lm is installed on Apple silicon).
- @pytest.mark.live tests call Claude and are skipped without ANTHROPIC_API_KEY.

Run:  pytest studio-5/01-local-inference -q
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

import starter as lab

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# The final chunk of a /api/generate stream, as printed in Ollama's API reference (docs/api.md).
DOC_FINAL = {
    "model": "llama3.2",
    "created_at": "2023-08-04T19:22:45.499127Z",
    "response": "",
    "done": True,
    "context": [1, 2, 3],
    "total_duration": 10706818083,
    "load_duration": 6338219291,
    "prompt_eval_count": 26,
    "prompt_eval_duration": 130079000,
    "eval_count": 259,
    "eval_duration": 4232710000,
}


def stream_events():
    return [tuple(e) for e in json.loads((FIXTURES / "ollama_chat_stream.json").read_text())["events"]]


# ---------------------------------------------------------------- 1. benchmarking math


def test_ns_to_s():
    assert lab.ns_to_s(1_500_000_000) == pytest.approx(1.5)


def test_tokens_per_second_matches_ollama_formula():
    # Ollama's docs: eval_count / eval_duration * 10^9.
    assert lab.tokens_per_second(259, lab.ns_to_s(4232710000)) == pytest.approx(61.19, abs=0.01)


def test_tokens_per_second_rejects_zero_duration():
    with pytest.raises(ValueError):
        lab.tokens_per_second(10, 0)


def test_parse_final_chunk_separates_load_prefill_decode():
    t = lab.parse_ollama_final(DOC_FINAL)
    assert t.load_s == pytest.approx(6.338, abs=0.001), "load time is reported separately"
    assert t.decode_tokens == 259 and t.decode_tps == pytest.approx(61.19, abs=0.01)
    assert t.prefill_tokens == 26 and t.prefill_tps == pytest.approx(199.88, abs=0.01)
    assert t.total_s == pytest.approx(10.707, abs=0.001)
    naive = t.decode_tokens / t.total_s
    assert naive < t.decode_tps / 2, "dividing by total_duration badly understates decode speed on a cold start"


def test_parse_final_chunk_handles_cached_prompt():
    chunk = dict(DOC_FINAL, prompt_eval_duration=0)
    del chunk["prompt_eval_count"]
    t = lab.parse_ollama_final(chunk)
    assert t.prefill_tokens == 0 and t.prefill_tps is None, "no prefill time means no prefill rate, not a crash"


def test_parse_final_chunk_requires_done():
    with pytest.raises(ValueError):
        lab.parse_ollama_final(dict(DOC_FINAL, done=False))


def test_summarize_drops_warmup_and_uses_nearest_rank_p90():
    s = lab.summarize([9.0, 1.0, 2.0, 3.0, 4.0], discard_first=1)
    assert s["n"] == 4 and s["median"] == pytest.approx(2.5)
    assert s["p90"] == 4.0 and s["min"] == 1.0 and s["max"] == 4.0
    s10 = lab.summarize([float(i) for i in range(1, 11)])
    assert s10["p90"] == 9.0, "nearest rank: ceil(0.9 * 10) = 9th smallest"


def test_summarize_rejects_empty():
    with pytest.raises(ValueError):
        lab.summarize([1.0], discard_first=1)


def test_bandwidth_ceiling():
    # 8B at Q4_K_M is about 4.9 GB; Apple lists 614 GB/s for the 40-core GPU M5 Max.
    assert lab.bandwidth_ceiling_tps(4.9, 614) == pytest.approx(125.3, abs=0.1)
    with pytest.raises(ValueError):
        lab.bandwidth_ceiling_tps(0, 614)


# ---------------------------------------------------------------- 2. stream parsing


def test_stream_ttft_skips_empty_and_thinking_chunks():
    r = lab.consume_ollama_stream(stream_events())
    assert r.ttft_s == pytest.approx(0.731), "TTFT is the first chunk with visible content, not the first chunk"
    assert r.final["done"] is True and r.final["eval_count"] == 41


def test_stream_text_is_concatenated_and_parses():
    r = lab.consume_ollama_stream(stream_events())
    assert lab.extract_json(r.text) == lab.EXPECTED


def test_stream_without_done_chunk_raises():
    truncated = [e for e in stream_events() if '"done": true' not in e[1]]
    with pytest.raises(ValueError):
        lab.consume_ollama_stream(truncated)


def test_stream_error_chunk_raises():
    events = stream_events()[:2] + [(0.5, json.dumps({"error": "model 'nope' not found"}))]
    with pytest.raises(RuntimeError, match="not found"):
        lab.consume_ollama_stream(events)


def test_stream_with_no_content_has_no_ttft():
    events = [(0.1, json.dumps({"message": {"role": "assistant", "content": ""}, "done": False})),
              (0.2, json.dumps(dict(DOC_FINAL, message={"role": "assistant", "content": ""})))]
    r = lab.consume_ollama_stream(events)
    assert r.ttft_s is None and r.text == ""


# ---------------------------------------------------------------- 3. reply parsing and scoring


def test_extract_json_plain():
    assert lab.extract_json((FIXTURES / "claude_reply.txt").read_text())["order_id"] == "A-20931"


def test_extract_json_fenced_with_prose():
    got = lab.extract_json((FIXTURES / "local_reply.txt").read_text())
    assert got["product"] == "Standing desk frame" and got["refund_requested"] is False


def test_extract_json_bare_object_inside_prose_with_braces_in_strings():
    text = 'Result: {"note": "use {curly} braces", "n": {"x": 1}} hope that helps'
    assert lab.extract_json(text) == {"note": "use {curly} braces", "n": {"x": 1}}


def test_extract_json_rejects_lists_and_garbage():
    with pytest.raises(ValueError):
        lab.extract_json("no json here")
    with pytest.raises(ValueError):
        lab.extract_json("[1, 2, 3]")


def test_score_fields_normalizes_strings_but_not_booleans():
    local = lab.extract_json((FIXTURES / "local_reply.txt").read_text())
    s = lab.score_fields(local, lab.EXPECTED)
    assert s["per_field"]["product"] is True, "case and whitespace differences in strings are not errors"
    assert s["per_field"]["refund_requested"] is False, "the customer asked for money back"
    assert s["accuracy"] == pytest.approx(0.8)


def test_score_fields_missing_and_wrong_type():
    s = lab.score_fields({"customer_name": "dana okafor", "refund_requested": 1}, lab.EXPECTED)
    assert s["per_field"]["customer_name"] is True
    assert s["per_field"]["refund_requested"] is False, "1 is not the boolean true"
    assert s["per_field"]["order_id"] is False, "a missing field is wrong"
    assert s["accuracy"] == pytest.approx(0.2)


def test_schema_and_prompt_are_consistent():
    assert set(lab.SCHEMA["required"]) == set(lab.EXPECTED) == set(lab.SCHEMA["properties"])
    assert lab.SCHEMA["additionalProperties"] is False
    assert "A-20931" in lab.build_prompt(lab.TICKET)


# ---------------------------------------------------------------- 4. local runtimes (free, optional)

needs_ollama = pytest.mark.skipif(
    not (lab.ollama_is_running() and lab.ollama_has_model(lab.DEFAULT_OLLAMA_MODEL)),
    reason=f"start Ollama and run `ollama pull {lab.DEFAULT_OLLAMA_MODEL}` to run this test",
)


@needs_ollama
def test_local_ollama_stream_and_timing():
    r = lab.run_ollama(lab.build_prompt(lab.TICKET))
    print(f"\nOllama: TTFT {r['ttft_s']:.2f}s, decode {r['decode_tps']:.1f} tok/s, load {r['load_s']:.2f}s")
    assert r["ttft_s"] is not None and r["ttft_s"] > 0
    assert r["decode_tps"] and r["decode_tps"] > 0
    lab.extract_json(r["text"])  # schema-constrained output should parse


@pytest.mark.skipif(not lab.mlx_available(), reason="mlx-lm is not installed (Apple silicon only)")
def test_local_mlx_stream_and_timing():
    r = lab.run_mlx(lab.build_prompt(lab.TICKET), max_tokens=120)
    print(f"\nMLX: TTFT {r['ttft_s']:.2f}s, decode {r['decode_tps']:.1f} tok/s, peak {r['peak_memory_gb']:.1f} GB")
    assert r["ttft_s"] is not None and r["decode_tps"] > 0


# ---------------------------------------------------------------- 5. Claude (costs a fraction of a cent)


@pytest.mark.live
def test_live_claude_extraction():
    anthropic = pytest.importorskip("anthropic")
    r = lab.run_claude(anthropic.Anthropic(), lab.build_prompt(lab.TICKET))
    score = lab.score_fields(lab.extract_json(r["text"]), lab.EXPECTED)
    print(f"\nClaude: TTFT {r['ttft_s']:.2f}s, total {r['total_s']:.2f}s, accuracy {score['accuracy']:.0%}")
    assert score["accuracy"] >= 0.8, score["per_field"]
