"""Tests for Studio 6 lab 02. Offline tests need no API key; @pytest.mark.live tests call Claude.

Run:  pytest studio-6/02-cost-latency -q
"""
from __future__ import annotations

import json
import random
from types import SimpleNamespace

import pytest

import starter as lab

DOC = (lab.SAMPLES_DIR / "handbook.md").read_text()


# ---------------------------------------------------------------- 1. dollars


def test_cost_prices_each_meter_separately():
    usage = {"input_tokens": 1000, "cache_creation_input_tokens": 2000,
             "cache_read_input_tokens": 10000, "output_tokens": 500}
    # Sonnet 5.5: 1000*2 + 2000*2.5 + 10000*0.1 + 500*10 = 13,000 millionths of a dollar
    assert lab.request_cost(usage, "claude-sonnet-5-5") == pytest.approx(0.013)


def test_cost_uses_one_hour_rate_from_breakdown():
    usage = {"input_tokens": 0, "cache_creation_input_tokens": 3000, "cache_read_input_tokens": 0,
             "output_tokens": 0,
             "cache_creation": {"ephemeral_5m_input_tokens": 1000, "ephemeral_1h_input_tokens": 2000}}
    # Opus 5.5: 1000 * 5.00 + 2000 * 8.00
    assert lab.request_cost(usage, "claude-opus-5-5") == pytest.approx(0.021)


def test_cost_treats_missing_meters_as_zero():
    assert lab.request_cost({"input_tokens": 2000, "output_tokens": 0,
                             "cache_creation_input_tokens": None}, "claude-haiku-5-5") == pytest.approx(0.0002)


def test_cost_rejects_unknown_model():
    with pytest.raises(KeyError):
        lab.request_cost({"input_tokens": 1, "output_tokens": 1}, "some-other-model")


def test_total_input_is_the_sum_of_three_meters():
    usage = {"input_tokens": 50, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 12000,
             "output_tokens": 400}
    assert lab.total_input(usage) == 12050


# ---------------------------------------------------------------- 2. percentiles


def test_percentile_nearest_rank():
    waits = [1.2, 0.9, 1.1, 8.0, 1.0, 1.3, 0.8, 1.4, 1.0, 1.2]
    assert lab.percentile(waits, 50) == 1.1
    assert lab.percentile(waits, 90) == 1.4
    assert lab.percentile(waits, 100) == 8.0
    assert lab.percentile([4.0], 99) == 4.0


def test_percentile_empty_raises():
    with pytest.raises(ValueError):
        lab.percentile([], 50)


# ---------------------------------------------------------------- 3. requests


def test_cached_request_puts_breakpoint_after_document_only():
    req = lab.build_request(DOC, "What is the late-change fee?", cached=True)
    assert set(req) == {"model", "max_tokens", "output_config", "system", "messages"}
    assert req["model"] == lab.MODEL
    system = req["system"]
    assert len(system) == 2 and system[0]["text"] == lab.INSTRUCTIONS
    assert "cache_control" not in system[0]
    assert system[1]["cache_control"] == {"type": "ephemeral"}
    assert system[1]["text"] == f"<handbook>\n{DOC}\n</handbook>"
    assert req["messages"] == [{"role": "user", "content": "What is the late-change fee?"}]


def test_baseline_request_has_no_cache_control_and_same_bytes_otherwise():
    base = lab.build_request(DOC, "q", cached=False)
    cached = lab.build_request(DOC, "q", cached=True)
    assert not any("cache_control" in block for block in base["system"])
    stripped = [{k: v for k, v in b.items() if k != "cache_control"} for b in cached["system"]]
    assert stripped == base["system"], "the two arms must differ only by the marker"


def test_system_prefix_is_identical_across_questions():
    a = lab.build_request(DOC, "first question", cached=True)
    b = lab.build_request(DOC, "a different question", cached=True)
    assert json.dumps(a["system"], sort_keys=True) == json.dumps(b["system"], sort_keys=True), (
        "anything that varies per request must sit after the breakpoint"
    )


def test_request_has_no_sampling_parameters():
    req = lab.build_request(DOC, "q", cached=True)
    for key in ("temperature", "top_p", "top_k"):
        assert key not in req


# ---------------------------------------------------------------- 4. timing, with a fake streaming client


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeStream:
    """Yields events at scripted times by moving the shared clock before each one."""

    def __init__(self, clock, script, usage, start):
        self.clock, self.script, self.usage, self.start = clock, script, usage, start

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for at, event in self.script:
            self.clock.now = self.start + at
            yield event

    def get_final_message(self):
        self.clock.now = self.start + self.script[-1][0] + 0.05
        return SimpleNamespace(stop_reason="end_turn", usage=self.usage, content=[])


def ev(type_, delta_type=None):
    return SimpleNamespace(type=type_, delta=SimpleNamespace(type=delta_type) if delta_type else None)


SCRIPT = [
    (0.40, ev("message_start")),
    (0.45, ev("content_block_start")),
    (0.90, ev("content_block_delta", "thinking_delta")),
    (1.70, ev("content_block_stop")),
    (1.75, ev("content_block_start")),
    (1.80, ev("content_block_delta", "text_delta")),
    (2.60, ev("content_block_delta", "text_delta")),
    (2.70, ev("message_stop")),
]


class FakeMessages:
    def __init__(self, clock):
        self.clock = clock
        self.calls = []

    def stream(self, **params):
        self.calls.append(params)
        cached = any("cache_control" in b for b in params["system"])
        first_cached = cached and not any(
            "cache_control" in b for p in self.calls[:-1] for b in p["system"]
        )
        usage = SimpleNamespace(
            input_tokens=30 if cached else 2746,
            cache_creation_input_tokens=2716 if first_cached else 0,
            cache_read_input_tokens=2716 if cached and not first_cached else 0,
            output_tokens=300,
            cache_creation=None,
        )
        start = self.clock.now  # the request was just sent
        return FakeStream(self.clock, SCRIPT, usage, start)


class FakeClient:
    def __init__(self):
        self.clock = FakeClock()
        self.messages = FakeMessages(self.clock)


def test_timed_call_records_three_timestamps_and_usage():
    client = FakeClient()
    rec = lab.timed_call(client, lab.build_request(DOC, "q", cached=False), clock=client.clock)
    assert rec["ttft_s"] == pytest.approx(0.40), "time of message_start"
    assert rec["first_text_s"] == pytest.approx(1.80), "first text delta, not the thinking delta"
    assert rec["total_s"] == pytest.approx(2.75), "measured after get_final_message()"
    assert rec["usage"]["input_tokens"] == 2746 and rec["usage"]["output_tokens"] == 300
    assert rec["model"] == lab.MODEL and rec["stop_reason"] == "end_turn"
    json.dumps(rec)  # records must be plain data you can log


def test_timed_call_without_text_reports_none():
    client = FakeClient()
    client.messages.stream = lambda **p: FakeStream(
        client.clock, [(0.3, ev("message_start")), (0.5, ev("message_stop"))],
        SimpleNamespace(input_tokens=10, output_tokens=0), client.clock.now)
    rec = lab.timed_call(client, lab.build_request(DOC, "q", cached=False), clock=client.clock)
    assert rec["first_text_s"] is None


def test_run_comparison_interleaves_arms_on_the_same_questions():
    client = FakeClient()
    qs = ["q1", "q2", "q3"]
    recs = lab.run_comparison(client, DOC, qs, clock=client.clock)
    assert [r["arm"] for r in recs] == ["baseline", "cached", "cached", "baseline", "baseline", "cached"]
    assert [r["question_index"] for r in recs] == [0, 0, 1, 1, 2, 2]
    sent = [c["messages"][0]["content"] for c in client.messages.calls]
    assert sent == ["q1", "q1", "q2", "q2", "q3", "q3"]
    cached = [r for r in recs if r["arm"] == "cached"]
    assert cached[0]["usage"]["cache_creation_input_tokens"] > 0
    assert all(r["usage"]["cache_read_input_tokens"] > 0 for r in cached[1:])


def test_run_comparison_alternates_across_rounds():
    client = FakeClient()
    recs = lab.run_comparison(client, DOC, ["a", "b"], rounds=2, clock=client.clock)
    assert len(recs) == 8
    assert [r["arm"] for r in recs][:4] == ["baseline", "cached", "cached", "baseline"]
    assert [r["round"] for r in recs] == [0, 0, 0, 0, 1, 1, 1, 1]


# ---------------------------------------------------------------- 5. analysis on recorded-shape fixtures


def test_summarize_fixture_arms():
    recs = lab.load_fixture("comparison.json")
    base = lab.summarize([r for r in recs if r["arm"] == "baseline"])
    cached = lab.summarize([r for r in recs if r["arm"] == "cached"])
    assert base["n"] == cached["n"] == 6
    assert base["cache_read_fraction"] == 0
    assert cached["cache_read_fraction"] == pytest.approx(13580 / 16463, rel=1e-6)
    assert base["mean_cost"] == pytest.approx(0.000423133, rel=1e-5)
    assert cached["mean_cost"] == pytest.approx(0.00023025, rel=1e-5)
    assert base["ttft_s"]["p50"] == 1.04 and cached["ttft_s"]["p50"] == 0.88
    assert base["total_s"]["p95"] == 4.38


def test_summarize_skips_missing_timings_and_rejects_empty():
    recs = lab.load_fixture("comparison.json")[:2]
    recs = [dict(r, first_text_s=None) for r in recs]
    s = lab.summarize(recs)
    assert s["first_text_s"] == {"p50": None, "p95": None}
    with pytest.raises(ValueError):
        lab.summarize([])


def test_compare_on_fixture_shows_cost_drop_and_small_latency_change():
    result = lab.compare(lab.load_fixture("comparison.json"))
    assert result["cost_ratio"] == pytest.approx(0.5442, abs=1e-3), (
        "on Haiku the cached prefix becomes cheap and output dominates what is left"
    )
    assert 0.7 < result["ttft_p50_ratio"] < 1.0
    assert "cost" in lab.format_report(result)


def test_cache_health_passes_a_healthy_arm():
    recs = lab.load_fixture("comparison.json")
    assert lab.cache_health([r for r in recs if r["arm"] == "cached"]) == []


def test_cache_health_flags_a_silent_invalidator():
    warnings = lab.cache_health(lab.load_fixture("broken_cached_arm.json"))
    assert warnings == [
        "no cache reads after the first request: look for a silent invalidator",
        "most warm requests rewrite the cache: the prefix is changing between requests",
    ]


def test_cache_health_flags_a_short_prompt_and_empty_input():
    short = [{"model": lab.MODEL, "usage": {"input_tokens": 300, "output_tokens": 50}}] * 2
    warnings = lab.cache_health(short)
    assert warnings[0] == "prompt is under 512 tokens, below the minimum cacheable length"
    assert lab.cache_health([]) == ["no records"]


def test_analysis_does_not_depend_on_record_order_within_an_arm():
    recs = lab.load_fixture("comparison.json")
    shuffled = recs[:]
    random.Random(7).shuffle(shuffled)
    assert lab.summarize([r for r in shuffled if r["arm"] == "baseline"]) == lab.summarize(
        [r for r in recs if r["arm"] == "baseline"]
    )


# ---------------------------------------------------------------- 6. live


@pytest.mark.live
def test_live_caching_comparison():
    import anthropic

    client = anthropic.Anthropic()
    records = lab.run_comparison(client, DOC, lab.QUESTIONS[:4])
    result = lab.compare(records)
    print("\n" + lab.format_report(result))
    cached = [r for r in records if r["arm"] == "cached"]
    for w in lab.cache_health(cached):
        print("WARNING:", w)
    assert all(r["stop_reason"] in ("end_turn", "stop_sequence") for r in records)
    assert any(r["usage"]["cache_read_input_tokens"] > 0 for r in cached[1:]), (
        "after the first cached request, later ones should read the prefix"
    )
    assert result["cost_ratio"] < 1.0
