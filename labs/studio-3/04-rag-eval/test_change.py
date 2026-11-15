"""Acceptance tests for CHANGE.md: a judge failure on one answer is recorded, not fatal.

They fail until the change is made. Run them on their own:

    pytest studio-3/04-rag-eval/test_change.py -q
"""
from __future__ import annotations

import pytest

import starter as lab

pytestmark = pytest.mark.change

FIXTURE = lab.load_fixture()
HUMAN = lab.load_human_labels()


class FlakyJudge:
    """Replays recorded judgments, but raises a chosen exception for every claim of the given cases."""

    def __init__(self, fail_ids, exc=None):
        self.inner = lab.RecordedJudge()
        self.fail_ids = set(fail_ids)
        self.exc = exc or lab.JudgeFailed("judge stopped with refusal")
        self.model = self.inner.model

    def __call__(self, case_id, claim, contexts):
        if case_id in self.fail_ids:
            raise self.exc
        return self.inner(case_id, claim, contexts)


def test_one_failure_does_not_stop_the_run():
    s = lab.evaluate(FIXTURE, FlakyJudge({"q7"}), human_labels=HUMAN)
    f = s["faithfulness"]
    assert f["judge_failed"] == ["q7"]
    assert f["per_case"]["q7"] is None
    assert f["n_scored"] == 6, "q6 abstained and q7 failed, so 6 of 8 answers are scored"
    assert f["n_abstained"] == 1, "a judge failure is not an abstention"


def test_no_failures_gives_an_empty_list():
    s = lab.evaluate(FIXTURE, lab.RecordedJudge(), human_labels=HUMAN)
    assert s["faithfulness"]["judge_failed"] == []
    assert s["faithfulness"]["n_scored"] == 7


def test_judge_check_skips_the_failed_answer():
    s = lab.evaluate(FIXTURE, FlakyJudge({"q7"}), human_labels=HUMAN)
    assert s["judge_agreement"]["n"] == 13, "16 labeled claims minus q7's 3"


def test_report_lists_judge_failures():
    failed = lab.build_report(lab.evaluate(FIXTURE, FlakyJudge({"q7"}), human_labels=HUMAN))
    clean = lab.build_report(lab.evaluate(FIXTURE, lab.RecordedJudge(), human_labels=HUMAN))
    section = failed.split("## Faithfulness")[1].split("## Judge check")[0]
    assert "Judge failures: q7" in section
    assert "Judge failures: none" in clean


def test_other_errors_still_raise():
    """Only JudgeFailed is tolerated. A bug (here a KeyError) must still stop the run loudly."""
    with pytest.raises(KeyError):
        lab.evaluate(FIXTURE, FlakyJudge({"q7"}, exc=KeyError("bug")), human_labels=HUMAN)
    s = lab.evaluate(FIXTURE, FlakyJudge({"q2"}), human_labels=HUMAN)
    assert s["faithfulness"]["judge_failed"] == ["q2"]
