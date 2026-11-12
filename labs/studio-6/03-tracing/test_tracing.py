"""Tests for Studio 6 lab 03. Offline tests need no API key; @pytest.mark.live tests call Claude.

Run:  pytest studio-6/03-tracing -q
The span tests need opentelemetry-sdk (pip install opentelemetry-sdk) and are skipped without it.
"""
from __future__ import annotations

import itertools
import json
import pathlib
from types import SimpleNamespace

import pytest

import starter as lab

HERE = pathlib.Path(__file__).parent
KEY = b"test-key-not-secret"


# ----------------------------------------------------------------- fakes


def response(text, *, model, input_tokens=100, output_tokens=20, cache_read=0, cache_write=0, stop_reason="end_turn"):
    return SimpleNamespace(
        id="msg_fake",
        model=model,
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
        ),
    )


class FakeOverloaded(Exception):
    pass


class FakeClient:
    """Returns queued responses (or raises queued exceptions) and records every call."""

    def __init__(self, *outcomes):
        self.calls = []
        self._outcomes = list(outcomes)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def ticking_clock(step=0.25):
    """Each call advances 0.25 s, so every model call measures exactly 250 ms."""
    counter = itertools.count()
    return lambda: next(counter) * step


TICKET = (
    "I was charged twice. Call me at (415) 555-0134 or write to maria.lopez@example.com. "
    "Our key is sk-test-AbCdEf0123456789XyZ."
)


def happy_client():
    return FakeClient(
        response("billing", model=lab.TRIAGE_MODEL, input_tokens=120, output_tokens=3),
        response("Thanks for reaching out, maria.lopez@example.com. We are checking the duplicate charge.",
                 model=lab.REPLY_MODEL, input_tokens=300, output_tokens=150, cache_read=2000),
    )


# ----------------------------------------------------------------- 1. redaction


@pytest.mark.parametrize(
    "text, expected",
    [
        ("write to maria.lopez@example.com today", "write to [EMAIL] today"),
        ("cc: a.b+tag@mail.example.co.uk", "cc: [EMAIL]"),
        ("call (415) 555-0134", "call [PHONE]"),
        ("call 415-555-0134 or 415.555.0134", "call [PHONE] or [PHONE]"),
        ("call +1 415 555 0134", "call [PHONE]"),
        ("my UK mobile is +447700900123", "my UK mobile is [PHONE]"),
        ("key sk-test-AbCdEf0123456789XyZ here", "key [SECRET] here"),
        ("admin key sk-ant-admin01-abcdefghijklmnop", "admin key [SECRET]"),
        ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload", "Authorization: [SECRET]"),
        ("api_key=abc123 and password: hunter2", "api_key=[SECRET] and password: [SECRET]"),
    ],
)
def test_redacts_known_patterns(text, expected):
    assert lab.redact(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Invoice dated 2026-11-11 for $1,299.00",
        "We are a team of 12, ticket #48213",
        "The token count was 4096",
        "Version 5.5 of the model",
    ],
)
def test_leaves_ordinary_text_alone(text):
    assert lab.redact(text) == text, "over-redaction destroys the debugging value of logs"


def test_secret_digits_are_not_mislabeled_as_phone():
    out = lab.redact("key sk-live-4155550134415555013441555501")
    assert out == "key [SECRET]"


def test_redaction_is_idempotent():
    once = lab.redact(TICKET)
    assert lab.redact(once) == once


def test_redact_value_walks_nested_structures_without_mutating():
    data = {"user": "lee@example.com", "args": ["call 415-555-0134", 42, None], "meta": {"ok": True}}
    out = lab.redact_value(data)
    assert out == {"user": "[EMAIL]", "args": ["call [PHONE]", 42, None], "meta": {"ok": True}}
    assert data["user"] == "lee@example.com", "return a new structure; don't mutate the input"


# Known false negatives. These document what a regex redactor misses (lesson 8). They are expected to fail;
# if you make one pass, check that you didn't add false positives above.
@pytest.mark.xfail(reason="obfuscated emails are a known false negative of regex redaction", strict=False)
def test_known_gap_obfuscated_email():
    assert "maria" not in lab.redact("reach me at maria dot lopez at example dot com")


@pytest.mark.xfail(reason="names need NER, not regex", strict=False)
def test_known_gap_names():
    assert "Maria Lopez" not in lab.redact("This is Maria Lopez from accounting")


@pytest.mark.xfail(reason="UK national format numbers are not covered", strict=False)
def test_known_gap_uk_national_format():
    assert lab.redact("ring 020 7946 0958") == "ring [PHONE]"


# ----------------------------------------------------------------- pseudonyms and cost


def test_pseudonymize_is_stable_keyed_and_opaque():
    a = lab.pseudonymize("maria.lopez@example.com", KEY)
    assert a == lab.pseudonymize("maria.lopez@example.com", KEY), "same input and key, same pseudonym"
    assert a.startswith("u_") and len(a) == 18
    assert a != lab.pseudonymize("maria.lopez@example.com", b"other-key"), "the key must matter (use HMAC)"
    assert "maria" not in a
    import hashlib

    assert a[2:] != hashlib.sha256(b"maria.lopez@example.com").hexdigest()[:16], "a bare hash is reversible by guessing"


def test_cost_opus_and_haiku():
    opus = lab.cost_usd("claude-opus-5-5", {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
                                             "cache_read_tokens": 0, "cache_write_tokens": 0})
    assert opus == pytest.approx(24.0)
    haiku = lab.cost_usd("claude-haiku-5-5", {"input_tokens": 2000, "output_tokens": 400,
                                              "cache_read_tokens": 0, "cache_write_tokens": 0})
    assert haiku == pytest.approx(2000 * 0.10 / 1e6 + 400 * 0.50 / 1e6)


def test_cost_prices_cache_reads_and_writes_separately():
    c = lab.cost_usd("claude-opus-5-5", {"input_tokens": 0, "output_tokens": 0,
                                          "cache_read_tokens": 1_000_000, "cache_write_tokens": 1_000_000})
    assert c == pytest.approx(0.20 + 5.00)


def test_cost_unknown_model_is_an_error_not_zero():
    with pytest.raises(ValueError):
        lab.cost_usd("claude-imaginary-9", {"input_tokens": 1, "output_tokens": 1,
                                            "cache_read_tokens": 0, "cache_write_tokens": 0})


# ----------------------------------------------------------------- records


def run_happy(capture_content=False):
    log = lab.ListLog()
    client = happy_client()
    out = lab.run_workflow(client, TICKET, user_id="maria.lopez@example.com", log=log, hmac_key=KEY,
                           capture_content=capture_content, clock=ticking_clock())
    return out, log.records, client


def test_workflow_writes_one_valid_record_per_step():
    out, records, client = run_happy()
    assert out["category"] == "billing" and out["status"] == "ok"
    assert [r["step"] for r in records] == ["triage", "reply"]
    assert [r["model"] for r in records] == [lab.TRIAGE_MODEL, lab.REPLY_MODEL]
    assert [c["model"] for c in client.calls] == [lab.TRIAGE_MODEL, lab.REPLY_MODEL]
    for r in records:
        assert set(r) == set(lab.RECORD_FIELDS), f"record fields must match the schema exactly: {sorted(set(r) ^ set(lab.RECORD_FIELDS))}"
        assert lab.validate_record(r) == [], lab.validate_record(r)


def test_record_values():
    _, (triage, reply), _ = run_happy()
    assert triage["prompt_version"] == lab.TRIAGE_PROMPT_VERSION and reply["prompt_version"] == lab.REPLY_PROMPT_VERSION
    assert triage["latency_ms"] == pytest.approx(250.0), "measure with the injected clock, in milliseconds"
    assert reply["cache_read_tokens"] == 2000 and reply["input_tokens"] == 300
    assert reply["cost_usd"] == pytest.approx((300 * 4 + 2000 * 0.20 + 150 * 20) / 1e6)
    assert triage["stop_reason"] == "end_turn" and triage["error_type"] is None
    assert triage["trace_id"] == reply["trace_id"] and len(triage["trace_id"]) == 32
    assert triage["span_id"] != reply["span_id"]
    assert triage["user"] == lab.pseudonymize("maria.lopez@example.com", KEY)


def test_no_content_by_default():
    _, records, _ = run_happy()
    assert all(r["input_preview"] is None and r["output_preview"] is None for r in records), (
        "content capture is opt-in (GenAI semantic conventions default)"
    )


def test_captured_content_is_redacted():
    _, records, _ = run_happy(capture_content=True)
    blob = json.dumps(records)
    for raw in ("maria.lopez@example.com", "555-0134", "sk-test-AbCdEf0123456789XyZ"):
        assert raw not in blob, f"{raw!r} leaked into the log"
    assert "[EMAIL]" in records[0]["input_preview"] and "[EMAIL]" in records[1]["output_preview"]
    assert all(len(r["input_preview"]) <= 200 for r in records)


def test_error_is_logged_then_raised():
    log = lab.ListLog()
    client = FakeClient(response("bug", model=lab.TRIAGE_MODEL), FakeOverloaded("529"))
    with pytest.raises(FakeOverloaded):
        lab.run_workflow(client, "export is broken", user_id="u1", log=log, hmac_key=KEY, clock=ticking_clock())
    assert [r["status"] for r in log.records] == ["ok", "error"]
    err = log.records[1]
    assert err["error_type"] == "FakeOverloaded"
    assert err["cost_usd"] == 0 and err["output_tokens"] == 0
    assert lab.validate_record(err) == []


def test_refused_triage_stops_the_workflow():
    log = lab.ListLog()
    client = FakeClient(response("", model=lab.TRIAGE_MODEL, output_tokens=0, stop_reason="refusal"))
    out = lab.run_workflow(client, "a ticket", user_id="u1", log=log, hmac_key=KEY, clock=ticking_clock())
    assert out["status"] == "refused" and out["reply"] is None
    assert len(client.calls) == 1, "don't call the reply step after a refused triage"
    assert log.records[0]["status"] == "refused"


def test_unknown_category_falls_back_to_other():
    assert lab.parse_category("Billing.") == "billing"
    assert lab.parse_category("Probably a refund question") == "other"


def test_validator_catches_bad_records():
    _, (good, _), _ = run_happy()
    assert lab.validate_record(good) == []
    bad = dict(good)
    del bad["model"]
    bad["latency_ms"] = -1
    bad["input_tokens"] = True
    bad["status"] = "weird"
    bad["output_preview"] = "contact lee@example.com"
    bad["extra"] = 1
    problems = lab.validate_record(bad)
    for expected in ("missing field: model", "negative: latency_ms", "bad type: input_tokens", "bad status: weird",
                     "unredacted: output_preview", "unexpected field: extra"):
        assert expected in problems, f"expected {expected!r} in {problems}"
    err = dict(good, status="error", error_type=None)
    assert "error without error_type" in lab.validate_record(err)


def test_jsonl_round_trip(tmp_path):
    log = lab.JsonlLog(tmp_path / "logs" / "run.jsonl")
    lab.run_workflow(happy_client(), TICKET, user_id="u1", log=log, hmac_key=KEY, clock=ticking_clock())
    rows = lab.read_jsonl(tmp_path / "logs" / "run.jsonl")
    assert len(rows) == 2 and all(lab.validate_record(r) == [] for r in rows)


# ----------------------------------------------------------------- aggregation and dashboard


def rec(trace, step, model, latency, cost, status="ok", tin=10, tout=5):
    return {"trace_id": trace, "step": step, "model": model, "latency_ms": latency, "cost_usd": cost,
            "status": status, "input_tokens": tin, "output_tokens": tout, "cache_read_tokens": 0,
            "cache_write_tokens": 0}


def test_percentile_nearest_rank():
    xs = [15, 20, 35, 40, 50]
    assert lab.percentile(xs, 50) == 35
    assert lab.percentile(xs, 95) == 50
    assert lab.percentile(xs, 30) == 20
    assert lab.percentile(xs, 100) == 50
    assert lab.percentile(list(range(1, 101)), 95) == 95
    assert lab.percentile([], 50) is None


def test_aggregate_small_log():
    records = [
        rec("t1", "triage", "h", 100, 0.001), rec("t1", "reply", "o", 2000, 0.010),
        rec("t2", "triage", "h", 300, 0.001), rec("t2", "reply", "o", 30000, 0.0, status="error", tin=0, tout=0),
        rec("t3", "triage", "h", 200, 0.001, status="refused", tout=0),
    ]
    agg = lab.aggregate(records)
    assert agg["traces"] == 3 and agg["failed_traces"] == 2
    assert agg["total_cost_usd"] == pytest.approx(0.013)
    assert agg["cost_per_trace_usd"] == pytest.approx(0.013 / 3)
    rows = {(r["step"], r["model"]): r for r in agg["rows"]}
    assert [(r["step"], r["model"]) for r in agg["rows"]] == [("reply", "o"), ("triage", "h")], "sort by step, model"
    tri, rep = rows[("triage", "h")], rows[("reply", "o")]
    assert tri["n"] == 3 and tri["refusal_rate"] == pytest.approx(1 / 3) and tri["error_rate"] == 0
    assert tri["p50_ms"] == 200 and tri["p95_ms"] == 300
    assert rep["error_rate"] == pytest.approx(0.5)
    assert rep["p95_ms"] == 30000, "failed calls count toward latency: a slow error is still slow"
    assert agg["trace_p95_ms"] == 30300, "trace latency is the sum of its steps"


def test_aggregate_sample_log_and_render():
    records = lab.read_jsonl(HERE / "samples" / "sample_log.jsonl")
    assert all(lab.validate_record(r) == [] for r in records), "the sample log follows the schema"
    agg = lab.aggregate(records)
    assert agg["traces"] == 60
    assert agg["total_cost_usd"] == pytest.approx(sum(r["cost_usd"] for r in records))
    md = lab.render_markdown(agg)
    assert md.startswith("# ")
    assert "- Traces: 60" in md
    assert f"- Total cost: ${agg['total_cost_usd']:.4f}" in md
    assert "| Step | Model | Calls | Error rate | Refusal rate | p50 | p95 | Input tokens | Output tokens | Cost |" in md
    assert md.count("\n| reply |") == 1 and md.count("\n| triage |") == 1


def test_render_formats_numbers():
    agg = lab.aggregate([rec("t1", "triage", "h", 1234.4, 0.00123), rec("t2", "triage", "h", 2000, 0.0, status="error")])
    md = lab.render_markdown(agg)
    assert "- Failed traces: 1 (50.0%)" in md
    assert "| triage | h | 2 | 50.0% | 0.0% | 1,234 ms | 2,000 ms | 20 | 10 | $0.0012 |" in md


def test_cli_dashboard(tmp_path):
    out = tmp_path / "dashboard.md"
    assert lab.main(["dashboard", str(HERE / "samples" / "sample_log.jsonl"), "--out", str(out)]) == 0
    assert "Cost per trace" in out.read_text()


# ----------------------------------------------------------------- spans (needs opentelemetry-sdk)


@pytest.fixture
def otel():
    sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = sdk_trace.TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter


def test_span_tree_and_genai_attributes(otel):
    tracer, exporter = otel
    log = lab.ListLog()
    lab.run_workflow(happy_client(), TICKET, user_id="u1", log=log, hmac_key=KEY, tracer=tracer,
                     capture_content=True, clock=ticking_clock())
    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert set(spans) == {lab.WORKFLOW, f"chat {lab.TRIAGE_MODEL}", f"chat {lab.REPLY_MODEL}"}
    root = spans[lab.WORKFLOW]
    triage, reply = spans[f"chat {lab.TRIAGE_MODEL}"], spans[f"chat {lab.REPLY_MODEL}"]
    assert root.parent is None
    assert triage.parent.span_id == root.context.span_id and reply.parent.span_id == root.context.span_id
    a = dict(reply.attributes)
    assert a["gen_ai.operation.name"] == "chat" and a["gen_ai.provider.name"] == "anthropic"
    assert a["gen_ai.request.model"] == lab.REPLY_MODEL
    assert a["gen_ai.prompt.version"] == lab.REPLY_PROMPT_VERSION
    assert tuple(a["gen_ai.response.finish_reasons"]) == ("end_turn",)
    assert a["gen_ai.usage.output_tokens"] == 150
    assert a["gen_ai.usage.input_tokens"] == 300 + 2000, "the convention's input count includes cached tokens"
    assert log.records[0]["trace_id"] == f"{root.context.trace_id:032x}", "records carry the real trace id"
    assert log.records[1]["span_id"] == f"{reply.context.span_id:016x}"
    everything = json.dumps([dict(s.attributes) for s in spans.values()])
    assert "maria.lopez@example.com" not in everything and "Thanks for reaching out" not in everything, (
        "keep content off spans; it lives (redacted, opt-in) in the log"
    )


def test_error_span_status(otel):
    from opentelemetry.trace import StatusCode

    tracer, exporter = otel
    client = FakeClient(response("bug", model=lab.TRIAGE_MODEL), FakeOverloaded("529"))
    with pytest.raises(FakeOverloaded):
        lab.run_workflow(client, "export is broken", user_id="u1", log=lab.ListLog(), hmac_key=KEY, tracer=tracer,
                         clock=ticking_clock())
    spans = {s.name: s for s in exporter.get_finished_spans()}
    failed = spans[f"chat {lab.REPLY_MODEL}"]
    assert failed.status.status_code == StatusCode.ERROR
    assert failed.attributes["error.type"] == "FakeOverloaded"
    assert any(e.name == "exception" for e in failed.events), "record_exception adds an exception event"
    assert spans[lab.WORKFLOW].status.status_code == StatusCode.ERROR


# ----------------------------------------------------------------- live


@pytest.mark.live
def test_live_workflow(tmp_path):
    import anthropic

    log = lab.JsonlLog(tmp_path / "live.jsonl")
    ticket = json.loads((HERE / "samples" / "tickets.jsonl").read_text().splitlines()[0])
    out = lab.run_workflow(anthropic.Anthropic(), ticket["text"], user_id=ticket["user"], log=log, hmac_key=KEY,
                           capture_content=True)
    rows = lab.read_jsonl(tmp_path / "live.jsonl")
    print(json.dumps(rows, indent=2))
    assert out["status"] in {"ok", "refused", "truncated"}
    assert all(lab.validate_record(r) == [] for r in rows)
    assert "maria.lopez@example.com" not in json.dumps(rows)
    print(lab.render_markdown(lab.aggregate(rows)))
