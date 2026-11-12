"""Tests for Studio 3, lab 01. Offline tests need no API key; @pytest.mark.live tests call Claude.

Run:  pytest studio-3/01-error-analysis -q
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from types import SimpleNamespace

import pytest

import starter as lab

DATA = lab.DATA_DIR


@pytest.fixture(scope="module")
def traces():
    return lab.load_traces(DATA / "traces.jsonl")


@pytest.fixture(scope="module")
def taxonomy():
    return lab.load_taxonomy(DATA / "taxonomy.json")


@pytest.fixture(scope="module")
def annotations(traces, taxonomy):
    return lab.load_annotations(DATA / "annotations.csv", traces, taxonomy)


def write_csv(path, rows, header=("trace_id", "outcome", "note", "failure_modes")):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


# ---------------------------------------------------------------- 1. loading


def test_loads_all_traces_with_types(traces):
    assert len(traces) == 36
    assert traces[0].trace_id == "t01" and traces[-1].trace_id == "t36", "keep file order"
    assert isinstance(traces[0].retrieved, tuple), "retrieved should be a tuple (Trace is frozen and hashable)"
    assert "QuickBooks Desktop" in traces[1].user_message


def test_load_traces_skips_blank_lines_and_rejects_bad_records(tmp_path):
    good = {f: "x" for f in lab.TRACE_FIELDS} | {"retrieved": []}
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps(good | {"trace_id": "a"}) + "\n\n" + json.dumps(good | {"trace_id": "b"}) + "\n")
    assert [t.trace_id for t in lab.load_traces(p)] == ["a", "b"]
    p.write_text(json.dumps(good | {"trace_id": "a"}) + "\n" + json.dumps(good | {"trace_id": "a"}) + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        lab.load_traces(p)
    broken = dict(good)
    del broken["bot_response"]
    p.write_text(json.dumps(broken) + "\n")
    with pytest.raises(ValueError, match="bot_response"):
        lab.load_traces(p)


def test_taxonomy_loads_and_validates(taxonomy, tmp_path):
    assert set(taxonomy) == {
        "invented_feature", "missed_handoff", "wrong_policy", "answered_wrong_question", "stale_pricing", "tone"
    }
    p = tmp_path / "tax.json"
    p.write_text(json.dumps({"x": {"definition": "d", "severity": 5}}))
    with pytest.raises(ValueError):
        lab.load_taxonomy(p)
    p.write_text(json.dumps({"x": {"definition": "  ", "severity": 2}}))
    with pytest.raises(ValueError):
        lab.load_taxonomy(p)
    p.write_text(json.dumps({"x": {"definition": "d", "severity": True}}))
    with pytest.raises(ValueError):
        lab.load_taxonomy(p)


def test_annotation_template_round_trip(traces, tmp_path):
    p = tmp_path / "template.csv"
    lab.write_annotation_template(traces, p)
    with open(p, newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == ["trace_id", "user_message", "bot_response", "outcome", "note", "failure_modes"]
    assert len(rows) == 36 and rows[4]["trace_id"] == "t05"
    assert rows[4]["bot_response"] == traces[4].bot_response, "commas and quotes must survive (use the csv module)"
    assert all(r["outcome"] == "" for r in rows)
    assert lab.load_annotations(p, traces) == [], "an untouched template has nothing annotated yet"


def test_parse_modes():
    assert lab.parse_modes(" tone ; invented_feature;;tone ") == ("tone", "invented_feature")
    assert lab.parse_modes("") == ()


# ---------------------------------------------------------------- 2. validation


def test_real_annotations_load(annotations):
    assert len(annotations) == 36
    t08 = next(a for a in annotations if a.trace_id == "t08")
    assert t08.outcome == "fail" and t08.failure_modes == ("invented_feature", "tone")


def test_partial_annotation_is_allowed(traces, tmp_path):
    p = write_csv(tmp_path / "a.csv", [["t01", "Pass", "", ""], ["t02", "", "", ""], ["t03", " FAIL ", "wrong refund window", ""]])
    got = lab.load_annotations(p, traces)
    assert [(a.trace_id, a.outcome) for a in got] == [("t01", "pass"), ("t03", "fail")], "normalize case and skip blanks"
    assert got[1].failure_modes == () and got[1].note == "wrong refund window"


def test_every_problem_is_reported_at_once(traces, taxonomy, tmp_path):
    p = write_csv(
        tmp_path / "bad.csv",
        [
            ["t01", "pass", "", "tone"],
            ["t99", "fail", "?", ""],
            ["t03", "maybe", "", ""],
            ["t04", "fail", "", ""],
            ["t05", "fail", "", "hallucination;tone"],
            ["t05", "pass", "", ""],
        ],
    )
    with pytest.raises(lab.AnnotationError) as info:
        lab.load_annotations(p, traces, taxonomy)
    lines = str(info.value).splitlines()
    assert lines == [
        "row 1 (t01): pass with failure modes",
        "row 2 (t99): unknown trace_id",
        "row 3 (t03): outcome must be pass or fail",
        "row 4 (t04): fail needs a note or a failure mode",
        "row 5 (t05): unknown failure mode: hallucination",
        "row 6 (t05): duplicate trace_id",
    ]


def test_taxonomy_check_is_optional(traces, tmp_path):
    p = write_csv(tmp_path / "a.csv", [["t02", "fail", "", "made_up_mode"]])
    assert lab.load_annotations(p, traces)[0].failure_modes == ("made_up_mode",), "without a taxonomy, accept any code"


# ---------------------------------------------------------------- 3. counting and priorities


def test_counts_failing_traces_per_mode(annotations):
    counts = lab.count_failure_modes(annotations)
    assert counts == Counter(
        invented_feature=9, missed_handoff=6, answered_wrong_question=5, tone=4, wrong_policy=3, stale_pricing=2
    )


def test_counts_ignore_passes_and_repeat_codes():
    anns = [
        lab.Annotation("a", "fail", "", ("tone", "tone")),
        lab.Annotation("b", "pass", "", ()),
        lab.Annotation("c", "fail", "note only", ()),
    ]
    assert lab.count_failure_modes(anns) == Counter(tone=1)
    assert lab.uncoded_failures(anns) == ["c"]


def test_summarize(annotations):
    s = lab.summarize(annotations)
    assert (s["annotated"], s["passed"], s["failed"]) == (36, 13, 23)
    assert s["pass_rate"] == pytest.approx(13 / 36)
    assert lab.summarize([])["pass_rate"] == 0.0


def test_prioritize_weights_by_severity_and_breaks_ties(annotations, taxonomy):
    ranked = lab.prioritize(lab.count_failure_modes(annotations), taxonomy, 36)
    assert [p.mode for p in ranked] == [
        "invented_feature", "missed_handoff", "answered_wrong_question", "wrong_policy", "tone", "stale_pricing"
    ], "wrong_policy (3 traces, severity 3) outranks tone (4 traces, severity 1); tone and stale_pricing tie on score, so count decides"
    top = ranked[0]
    assert (top.count, top.severity) == (9, 3)
    assert top.rate == pytest.approx(0.25) and top.score == pytest.approx(0.75)


def test_prioritize_name_is_last_tie_breaker():
    tax = {"b": {"definition": "x", "severity": 2}, "a": {"definition": "x", "severity": 2}}
    assert [p.mode for p in lab.prioritize(Counter(b=1, a=1), tax, 10)] == ["a", "b"]


# ---------------------------------------------------------------- 4. report


def test_report_structure(traces, annotations, taxonomy):
    report = lab.render_report(traces, annotations, taxonomy)
    assert report.startswith("# Error analysis report")
    assert "Annotated 36 of 36 traces: 13 pass, 23 fail (pass rate 36.1%)." in report
    assert "| Rank | Failure mode | Traces | Rate | Severity | Score |" in report
    assert "| 1 | invented_feature | 9 | 25.0% | 3 | 0.75 |" in report
    assert "| 4 | wrong_policy | 3 | 8.3% | 3 | 0.25 |" in report
    assert "### 1. invented_feature" in report and "### 3. answered_wrong_question" in report
    assert "### 4." not in report, "only top_k issues get a section"
    assert "Examples: t02, t08, t13" in report
    assert "## Needs axial coding" not in report, "every failure in the sample data is coded"
    caveats = report.index("## Caveats")
    assert report.index("## Top issues") < caveats and "Rates come from 36 annotated traces" in report[caveats:]


def test_report_lists_uncoded_failures(traces, taxonomy):
    anns = [lab.Annotation("t01", "pass", "", ()), lab.Annotation("t02", "fail", "weird answer", ())]
    report = lab.render_report(traces, anns, taxonomy, top_k=2)
    assert "Annotated 2 of 36 traces: 1 pass, 1 fail (pass rate 50.0%)." in report
    assert "## Needs axial coding" in report and "t02" in report.split("## Needs axial coding")[1]


# ---------------------------------------------------------------- 5. synthetic inputs (offline parts)


def test_make_tuples_cross_product_and_filter():
    dims = {"topic": ["refund", "security"], "plan": ["Starter", "Pro"], "style": ["terse"]}
    all_t = lab.make_tuples(dims)
    assert all_t == [
        {"topic": "refund", "plan": "Starter", "style": "terse"},
        {"topic": "refund", "plan": "Pro", "style": "terse"},
        {"topic": "security", "plan": "Starter", "style": "terse"},
        {"topic": "security", "plan": "Pro", "style": "terse"},
    ]
    some = lab.make_tuples(dims, exclude=lambda t: t["topic"] == "security" and t["plan"] == "Starter")
    assert len(some) == 3 and {"topic": "security", "plan": "Starter", "style": "terse"} not in some
    assert len(lab.make_tuples(lab.DIMENSIONS)) == 24


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0)


def reply(text, stop="end_turn"):
    parsed = lab.SyntheticQuery(query=text) if text is not None else None
    return SimpleNamespace(stop_reason=stop, parsed_output=parsed)


def test_generate_queries_one_call_per_tuple():
    tuples = lab.make_tuples({"topic": ["refund", "security"], "plan": ["Pro"]})
    client = SimpleNamespace(messages=FakeMessages([reply("can i get my money back"), reply("someone is in my account")]))
    got = lab.generate_queries(client, tuples)
    assert got == [
        {"dimensions": tuples[0], "query": "can i get my money back"},
        {"dimensions": tuples[1], "query": "someone is in my account"},
    ]
    first = client.messages.calls[0]
    assert first["output_format"] is lab.SyntheticQuery and first["model"] == lab.MODEL
    assert "topic: refund" in first["messages"][0]["content"], "each call carries its own tuple"
    assert not {"temperature", "top_p", "top_k"} & set(first), "sampling parameters are rejected on the current API"


@pytest.mark.parametrize("bad", [reply(None, "refusal"), reply("cut", "max_tokens"), reply(None)])
def test_generate_queries_fails_loudly(bad):
    client = SimpleNamespace(messages=FakeMessages([bad]))
    with pytest.raises(lab.GenerationFailed):
        lab.generate_queries(client, [{"topic": "refund"}])


# ---------------------------------------------------------------- live


@pytest.mark.live
def test_live_generation_differs_by_tuple():
    import anthropic

    tuples = [
        {"topic": "refund", "plan": "Starter", "style": "terse"},
        {"topic": "account security", "plan": "Pro", "style": "frustrated"},
    ]
    got = lab.generate_queries(anthropic.Anthropic(), tuples)
    for g in got:
        print(g["dimensions"], "->", g["query"])
    assert all(len(g["query"]) > 10 for g in got)
    assert got[0]["query"] != got[1]["query"]
