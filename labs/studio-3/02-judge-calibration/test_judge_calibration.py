"""Tests for Studio 3 lab 02. Offline tests need no API key; @pytest.mark.live tests call Claude.

Run:  pytest studio-3/02-judge-calibration -q
"""
from __future__ import annotations

import math
import pathlib
import random
from types import SimpleNamespace

import pytest

import starter as lab

DATA = pathlib.Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def examples():
    return lab.load_examples(DATA / "labeled.jsonl")


# ---------------------------------------------------------------- 1. data and split


def test_load_examples(examples):
    assert len(examples) == 40
    assert {e.human_label for e in examples} == {"pass", "fail"}
    assert sum(e.human_label == "pass" for e in examples) == 24


def test_load_rejects_unknown_labels(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"id": "x1", "question": "q", "reply": "r", "human_label": "maybe", "human_critique": "c"}\n')
    with pytest.raises(ValueError):
        lab.load_examples(bad)


def test_split_is_disjoint_and_complete(examples):
    dev, test = lab.split_dev_test(examples)
    dev_ids, test_ids = {e.id for e in dev}, {e.id for e in test}
    assert not dev_ids & test_ids, "an example in both splits leaks test data into prompt iteration"
    assert dev_ids | test_ids == {e.id for e in examples}


def test_split_is_stratified(examples):
    dev, test = lab.split_dev_test(examples)
    assert len(test) == 20 and len(dev) == 20
    assert sum(e.human_label == "pass" for e in test) == 12, "each split should keep the 60/40 pass/fail mix"
    assert sum(e.human_label == "fail" for e in test) == 8


def test_split_is_deterministic_and_order_independent(examples):
    first = lab.split_dev_test(examples)
    shuffled = examples[:]
    random.Random(7).shuffle(shuffled)
    second = lab.split_dev_test(shuffled)
    assert [e.id for e in first[1]] == [e.id for e in second[1]], "the split must not depend on input order"
    assert [e.id for e in first[1]] == sorted(e.id for e in first[1]), "return each split sorted by id"


def test_split_matches_reference_hashing(examples):
    _, test = lab.split_dev_test(examples)
    assert [e.id for e in test] == [
        "t02", "t04", "t05", "t06", "t07", "t10", "t11", "t13", "t18", "t20",
        "t21", "t23", "t24", "t31", "t32", "t33", "t34", "t35", "t37", "t39",
    ], "order each label group by sha256(f'{seed}:{id}') and take the first round(n * test_fraction)"


def test_changing_the_seed_changes_the_split(examples):
    a = {e.id for e in lab.split_dev_test(examples, seed="one")[1]}
    b = {e.id for e in lab.split_dev_test(examples, seed="two")[1]}
    assert a != b


# ---------------------------------------------------------------- 2. metrics


def test_confusion_counts():
    human = ["pass", "pass", "fail", "fail", "pass"]
    judge = ["pass", "fail", "pass", "fail", "pass"]
    assert lab.confusion(human, judge) == {"tp": 2, "fn": 1, "fp": 1, "tn": 1}


def test_kappa_hand_computed():
    # p_o = 0.9; both raters say pass 60% of the time, so p_e = 0.6*0.6 + 0.4*0.4 = 0.52
    human = ["pass"] * 12 + ["fail"] * 8
    judge = ["pass"] * 11 + ["fail"] + ["pass"] + ["fail"] * 7
    assert math.isclose(lab.cohen_kappa(human, judge), (0.9 - 0.52) / (1 - 0.52))


def test_kappa_perfect_chance_and_worse():
    h = ["pass", "fail", "pass", "fail"]
    assert math.isclose(lab.cohen_kappa(h, h), 1.0)
    assert math.isclose(lab.cohen_kappa(h, ["pass", "pass", "fail", "fail"]), 0.0), "agreement at chance level is kappa 0"
    assert lab.cohen_kappa(h, ["fail", "pass", "fail", "pass"]) < 0, "systematic disagreement is negative"


def test_kappa_undefined_when_both_raters_are_constant():
    assert math.isnan(lab.cohen_kappa(["pass"] * 5, ["pass"] * 5))


def test_always_pass_judge_has_high_accuracy_and_useless_tnr():
    human = ["pass"] * 9 + ["fail"]
    m = lab.agreement_metrics(human, ["pass"] * 10)
    assert math.isclose(m["accuracy"], 0.9)
    assert math.isclose(m["tpr"], 1.0)
    assert m["tnr"] == 0.0
    assert math.isclose(m["kappa"], 0.0), "a constant judge carries no information beyond chance"


def test_recorded_v1_and_v2_on_dev(examples):
    dev, _ = lab.split_dev_test(examples)
    v1 = lab.score_judge(dev, lab.load_recorded("v1", DATA / "recorded_judge.jsonl"))
    v2 = lab.score_judge(dev, lab.load_recorded("v2", DATA / "recorded_judge.jsonl"))
    assert math.isclose(v1["accuracy"], 0.40) and math.isclose(v1["tnr"], 0.125)
    assert math.isclose(v2["accuracy"], 0.95) and math.isclose(v2["tpr"], 1.0) and math.isclose(v2["tnr"], 0.875)
    assert v2["kappa"] > 0.85 > v1["kappa"]


def test_recorded_v2_on_test_is_a_bit_worse_than_dev(examples):
    dev, test = lab.split_dev_test(examples)
    rec = lab.load_recorded("v2", DATA / "recorded_judge.jsonl")
    d, t = lab.score_judge(dev, rec), lab.score_judge(test, rec)
    assert math.isclose(t["accuracy"], 0.90)
    assert math.isclose(t["kappa"], (0.9 - 0.52) / 0.48)
    assert t["kappa"] < d["kappa"], "prompts tuned on dev usually score a little lower on held-out data"


def test_errors_are_excluded_not_scored_as_fail(examples):
    dev, _ = lab.split_dev_test(examples)
    rec = dict(lab.load_recorded("v2", DATA / "recorded_judge.jsonl"))
    rec[dev[0].id] = None
    del rec[dev[1].id]
    m = lab.score_judge(dev, rec)
    assert m["errors"] == 2
    assert m["n"] == 18


# ---------------------------------------------------------------- 3. corrected pass rate


def test_correction_recovers_the_true_rate():
    p, tpr, tnr = 0.7, 0.9, 0.8
    observed = tpr * p + (1 - tnr) * (1 - p)  # 0.69
    assert math.isclose(lab.corrected_pass_rate(observed, tpr, tnr), p)


def test_perfect_judge_needs_no_correction():
    assert math.isclose(lab.corrected_pass_rate(0.42, 1.0, 1.0), 0.42)


def test_correction_clips_to_unit_interval():
    assert lab.corrected_pass_rate(0.99, 0.9, 0.8) == 1.0
    assert lab.corrected_pass_rate(0.05, 0.9, 0.8) == 0.0


def test_correction_refuses_an_uninformative_judge():
    with pytest.raises(ValueError):
        lab.corrected_pass_rate(0.6, 0.5, 0.5)
    with pytest.raises(ValueError):
        lab.corrected_pass_rate(0.6, 0.3, 0.4)


# ---------------------------------------------------------------- 4. the judge call, with a fake client


def test_verdict_schema_puts_critique_first_and_is_closed():
    schema = lab.Verdict.model_json_schema()
    assert list(schema["properties"]) == ["critique", "verdict"], "generate the critique before the verdict"
    assert schema.get("additionalProperties") is False
    assert schema["properties"]["verdict"].get("enum") == ["pass", "fail"]
    assert all(p.get("description") for p in schema["properties"].values()), "describe every field"


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


def ok(verdict="fail", critique="Rule 5 says a $6 fee applies."):
    return SimpleNamespace(stop_reason="end_turn", parsed_output=lab.Verdict(critique=critique, verdict=verdict))


def test_judge_call_shape(examples):
    client = FakeClient(ok())
    result = lab.judge(client, examples[0], "POLICY TEXT")
    (call,) = client.messages.calls
    assert call["output_format"] is lab.Verdict
    assert call["model"] == lab.MODEL
    assert call["output_config"].get("effort") in {"low", "medium", "high", "xhigh", "max"}, "set effort explicitly"
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in call, f"{banned} is rejected on the current API version"
    last = call["messages"][-1]
    assert last["role"] == "user"
    text = str(last["content"])
    assert "POLICY TEXT" in text and examples[0].reply in text and examples[0].question in text
    assert "<reply>" in text, "wrap the reply in tags so the judge treats it as data"
    assert result.status == "ok" and result.verdict == "fail" and "Rule 5" in result.critique


def test_judge_handles_refusal_and_truncation(examples):
    refused = lab.judge(FakeClient(SimpleNamespace(stop_reason="refusal", parsed_output=None)), examples[0], "P")
    assert refused.status == "refusal" and refused.verdict is None
    cut = lab.judge(FakeClient(SimpleNamespace(stop_reason="max_tokens", parsed_output=None)), examples[0], "P")
    assert cut.status == "truncated" and cut.verdict is None


def test_system_prompt_says_length_does_not_matter():
    text = lab.JUDGE_SYSTEM.lower()
    assert "length" in text or "long" in text, "tell the judge not to reward length (verbosity bias)"


# ---------------------------------------------------------------- 5. live


@pytest.mark.live
def test_live_judge_on_two_clear_cases(examples):
    import anthropic

    client = anthropic.Anthropic()
    policy = (DATA / "policy.txt").read_text()
    by_id = {e.id: e for e in examples}
    good, bad = by_id["t02"], by_id["t10"]  # accurate refund timeline; invented "no fee"
    r_good, r_bad = lab.judge(client, good, policy), lab.judge(client, bad, policy)
    print("\n", r_good, "\n", r_bad)
    assert r_good.status == "ok" and r_good.verdict == "pass"
    assert r_bad.status == "ok" and r_bad.verdict == "fail"
