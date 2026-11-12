"""Tests for Studio 3 lab 04. Offline tests need no API key; @pytest.mark.live tests call Claude.

Run:  pytest studio-3/04-rag-eval -q
"""
from __future__ import annotations

import statistics
from types import SimpleNamespace

import pytest

import starter as lab

FIXTURE = lab.load_fixture()
CASES = {c["id"]: c for c in FIXTURE["cases"]}
CHUNKS = FIXTURE["chunks"]


# ---------------------------------------------------------------- 1. retrieval metrics


def test_recall_counts_relevant_items_in_top_k():
    retrieved = ["a", "b", "c", "d"]
    assert lab.recall_at_k(retrieved, ["c", "z"], 3) == 0.5, "one of two relevant items is in the top 3"
    assert lab.recall_at_k(retrieved, ["d"], 3) == 0.0, "d is at rank 4, outside the top 3"
    assert lab.recall_at_k(retrieved, ["d"], 4) == 1.0


def test_recall_ignores_duplicate_relevant_ids():
    assert lab.recall_at_k(["a", "b"], ["a", "a"], 2) == 1.0


def test_recall_undefined_without_relevant_items():
    with pytest.raises(ValueError):
        lab.recall_at_k(["a"], [], 1)


def test_precision_divides_by_k():
    assert lab.precision_at_k(["a", "b", "c"], ["a", "c"], 3) == pytest.approx(2 / 3)
    assert lab.precision_at_k(["a"], ["a"], 5) == pytest.approx(0.2), "divide by k even when fewer items came back"


def test_reciprocal_rank():
    assert lab.reciprocal_rank(["x", "y", "a"], ["a"]) == pytest.approx(1 / 3)
    assert lab.reciprocal_rank(["a", "b"], ["b", "a"]) == 1.0, "use the FIRST relevant item"
    assert lab.reciprocal_rank(["x", "y"], ["a"]) == 0.0


def test_retrieval_metrics_on_fixture():
    m = lab.retrieval_metrics(FIXTURE["cases"], (3, 5))
    assert set(m) == {"recall@3", "precision@3", "recall@5", "precision@5", "mrr"}
    assert m["recall@5"] == pytest.approx(6.5 / 8)
    assert m["recall@3"] == pytest.approx(5.5 / 8), "q3's relevant chunk is at rank 4, so it only counts at k=5"
    assert m["mrr"] == pytest.approx(5.75 / 8)
    assert m["precision@5"] == pytest.approx(0.2)


# ---------------------------------------------------------------- 2. claims and faithfulness


def test_split_claims_removes_citations_and_short_fragments():
    claims = lab.split_claims("Yes. Requests need approval two weeks ahead [pto-3]. Ask your manager first [pto-3, rem-1]!")
    assert claims == ["Requests need approval two weeks ahead.", "Ask your manager first!"]


def test_split_claims_on_fixture_answer():
    assert lab.split_claims(CASES["q7"]["answer"]) == [
        "Corporate cards are issued to employees who travel more than four times per year.",
        "You can request one from the finance team.",
        "Cards come with a $5,000 monthly limit.",
    ]


def test_split_claims_does_not_split_inside_numbers():
    assert lab.split_claims("The limit is $60.50 per day for meals.") == ["The limit is $60.50 per day for meals."]


class ScriptedJudge:
    """Says a claim is unsupported if it contains any of the given words; records every call."""

    def __init__(self, *bad_words):
        self.bad = bad_words
        self.calls = []

    def __call__(self, case_id, claim, contexts):
        self.calls.append((case_id, claim, contexts))
        return not any(w in claim for w in self.bad)


def test_faithfulness_is_fraction_of_supported_claims():
    judge = ScriptedJudge("$5,000")
    assert lab.faithfulness(CASES["q7"], CHUNKS, judge) == pytest.approx(2 / 3)
    case_id, _, contexts = judge.calls[0]
    assert case_id == "q7"
    assert contexts == [CHUNKS[c] for c in CASES["q7"]["retrieved"]], "pass the retrieved chunk TEXTS in rank order"


def test_abstention_is_not_scored_and_not_judged():
    judge = ScriptedJudge()
    assert lab.faithfulness(CASES["q6"], CHUNKS, judge) is None, "an abstention is not a faithful answer; report it separately"
    assert judge.calls == [], "don't pay to judge an abstention"


def test_recorded_judge_matches_your_claims():
    judge = lab.RecordedJudge()
    for case in FIXTURE["cases"]:
        lab.faithfulness(case, CHUNKS, judge)  # raises KeyError if split_claims differs from the recorded text


# ---------------------------------------------------------------- 3. judge agreement


def test_judge_agreement_rates():
    judge = [True, True, True, False, True, False]
    human = [True, True, False, False, False, True]
    a = lab.judge_agreement(judge, human)
    assert a["tpr"] == pytest.approx(2 / 3), "humans said supported 3 times; the judge agreed twice"
    assert a["tnr"] == pytest.approx(1 / 3), "humans said unsupported 3 times; the judge caught one"
    assert a["n"] == 6


def test_judge_agreement_needs_both_classes_and_equal_lengths():
    with pytest.raises(ValueError):
        lab.judge_agreement([True, True], [True, True])
    with pytest.raises(ValueError):
        lab.judge_agreement([True], [True, False])


# ---------------------------------------------------------------- 4. bootstrap


def test_bootstrap_is_reproducible_and_brackets_the_mean():
    values = [1.0, 0.0, 1.0, 1.0, 0.5, 1.0, 0.0, 1.0, 1.0, 0.75]
    lo, hi = lab.bootstrap_ci(values, seed=7)
    assert (lo, hi) == lab.bootstrap_ci(values, seed=7), "same seed, same interval"
    assert lo <= statistics.fmean(values) <= hi
    assert 0.0 <= lo < hi <= 1.0


def test_bootstrap_constant_values_have_zero_width():
    assert lab.bootstrap_ci([0.8] * 12) == pytest.approx((0.8, 0.8))


def test_bootstrap_narrows_with_more_data():
    small = [1.0, 0.0] * 5
    large = [1.0, 0.0] * 200
    w_small = lab.bootstrap_ci(small)[1] - lab.bootstrap_ci(small)[0]
    w_large = lab.bootstrap_ci(large)[1] - lab.bootstrap_ci(large)[0]
    assert w_large < w_small / 3, "40x the data should shrink the interval by roughly sqrt(40)"


def test_bootstrap_rejects_empty():
    with pytest.raises(ValueError):
        lab.bootstrap_ci([])


# ---------------------------------------------------------------- 5. the live judge, with a fake client


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response

    def create(self, **kwargs):
        raise AssertionError("use client.messages.parse() with output_format=Verdict")


class FakeClient:
    def __init__(self, response):
        self.messages = FakeMessages(response)


def test_judge_claim_uses_structured_outputs():
    verdict = lab.Verdict(reason="Passage 1 states it.", supported=True)
    client = FakeClient(SimpleNamespace(stop_reason="end_turn", parsed_output=verdict))
    out = lab.judge_claim(client, "Alcohol is not reimbursable.", [CHUNKS["exp-1"]])
    assert out is verdict
    (call,) = client.messages.calls
    assert call["output_format"] is lab.Verdict
    assert call["model"] == lab.JUDGE_MODEL
    assert call["system"] == lab.JUDGE_SYSTEM
    content = str(call["messages"][-1]["content"])
    assert "Alcohol is not reimbursable." in content and CHUNKS["exp-1"] in content
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in call, f"{banned} is rejected on the current API version"


@pytest.mark.parametrize("reason", ["refusal", "max_tokens"])
def test_judge_claim_fails_loudly(reason):
    client = FakeClient(SimpleNamespace(stop_reason=reason, parsed_output=None))
    with pytest.raises(lab.JudgeFailed):
        lab.judge_claim(client, "x y z", ["passage"])


# ---------------------------------------------------------------- 6. evaluate and report


@pytest.fixture(scope="module")
def summary():
    return lab.evaluate(FIXTURE, lab.RecordedJudge(), human_labels=lab.load_human_labels(), judge_name="recorded judge")


def test_evaluate_on_fixture(summary):
    f = summary["faithfulness"]
    assert f["n_scored"] == 7 and f["n_abstained"] == 1
    assert f["mean"] == pytest.approx((5 + 2 / 3 + 2 / 3) / 7)
    lo, hi = f["ci"]
    assert lo <= f["mean"] <= hi
    assert summary["retrieval_misses"] == ["q4", "q6"]
    a = summary["judge_agreement"]
    assert a["n"] == 16 and a["tpr"] == pytest.approx(1.0) and a["tnr"] == pytest.approx(0.5)


def test_report_structure_and_numbers(summary):
    report = lab.build_report(summary)
    headings = ["# RAG evaluation report", "## Bottom line", "## Retrieval", "## Faithfulness", "## Judge check", "## Caveats"]
    positions = [report.find(h) for h in headings]
    assert all(p >= 0 for p in positions), f"missing a heading: {dict(zip(headings, positions))}"
    assert positions == sorted(positions), "headings must appear in the required order"
    assert "0.90" in report, "faithfulness mean, two decimals"
    assert "0.8125" not in report and "0.81" in report, "recall@5 formatted with two decimals"
    assert "q4" in report and "q6" in report, "name the questions with retrieval misses"
    assert "TNR 0.50" in report or "TNR: 0.50" in report or "0.50" in report.split("## Judge check")[1]
    assert "8" in report.split("## Caveats")[1], "state the sample size in the caveats"
    assert report.count("|") >= 12, "retrieval metrics belong in a Markdown table"


def test_report_bottom_line_is_short_and_plain(summary):
    report = lab.build_report(summary)
    bottom = report.split("## Bottom line")[1].split("## Retrieval")[0]
    assert "CI" in bottom or "interval" in bottom, "give the uncertainty, not just the point estimate"
    assert len(bottom.split()) <= 120, "the bottom line is for a busy stakeholder: keep it under about 120 words"
    assert "|" not in bottom, "no tables in the bottom line"


def test_report_without_judge_check_says_so():
    s = lab.evaluate(FIXTURE, lab.RecordedJudge(), human_labels=None, judge_name="recorded judge")
    report = lab.build_report(s)
    check = report.split("## Judge check")[1].split("## Caveats")[0].lower()
    assert "not been checked" in check or "unverified" in check or "not checked" in check


# ---------------------------------------------------------------- 7. live


@pytest.mark.live
def test_live_judge_separates_supported_from_invented():
    import anthropic

    client = anthropic.Anthropic()
    contexts = [CHUNKS["exp-3"], CHUNKS["exp-1"]]
    good = lab.judge_claim(client, "Corporate card requests go to the finance team.", contexts)
    bad = lab.judge_claim(client, "Cards come with a $5,000 monthly limit.", contexts)
    print(f"\nsupported claim -> {good.supported}: {good.reason}\ninvented claim  -> {bad.supported}: {bad.reason}")
    assert good.supported is True
    assert bad.supported is False
