"""Acceptance tests for this lab's CHANGE.md task: pass rate by segment.

Run:  pytest studio-3/01-error-analysis/test_change.py -q
"""
from __future__ import annotations

import pytest

import starter as lab

pytestmark = pytest.mark.change

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


def test_pass_rate_by_channel(traces, annotations):
    got = lab.pass_rate_by(traces, annotations, "channel")
    assert list(got) == ["chat", "email"], "keys sorted A to Z"
    assert (got["chat"]["annotated"], got["chat"]["passed"]) == (32, 12)
    assert (got["email"]["annotated"], got["email"]["passed"]) == (4, 1)
    assert got["email"]["pass_rate"] == pytest.approx(0.25)


def test_pass_rate_by_plan(traces, annotations):
    got = lab.pass_rate_by(traces, annotations, "plan")
    assert list(got) == ["Pro", "Starter"]
    assert got["Pro"] == {"annotated": 20, "passed": 7, "pass_rate": pytest.approx(0.35)}
    assert got["Starter"] == {"annotated": 16, "passed": 6, "pass_rate": pytest.approx(0.375)}


def test_only_annotated_traces_count(traces):
    anns = [lab.Annotation("t01", "pass", "", ()), lab.Annotation("t02", "fail", "x", ("invented_feature",))]
    got = lab.pass_rate_by(traces, anns, "channel")
    assert sum(v["annotated"] for v in got.values()) == 2, "unannotated traces must not dilute the rate"


def test_unknown_field_is_rejected(traces, annotations):
    for bad in ("bot_response", "trace_id", "region"):
        with pytest.raises(ValueError):
            lab.pass_rate_by(traces, annotations, bad)


def test_report_section_is_optional_and_placed_before_caveats(traces, annotations, taxonomy):
    plain = lab.render_report(traces, annotations, taxonomy)
    assert "## Pass rate by" not in plain, "default report is unchanged"
    report = lab.render_report(traces, annotations, taxonomy, segment_by="channel")
    assert "## Pass rate by channel" in report
    assert "| channel | Annotated | Passed | Pass rate |" in report
    assert "| chat | 32 | 12 | 37.5% |" in report and "| email | 4 | 1 | 25.0% |" in report
    assert report.index("## Top issues") < report.index("## Pass rate by channel") < report.index("## Caveats")
