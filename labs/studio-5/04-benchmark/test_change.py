"""Acceptance tests for CHANGE.md (Studio 5 lab 04): paired differences per field.

Run:  pytest studio-5/04-benchmark/test_change.py -q
"""
from __future__ import annotations

import copy
import json
import pathlib
import random
import re

import pytest

import starter as lab

pytestmark = pytest.mark.change

FIX = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def cases():
    return lab.load_test_set(FIX / "test_set.jsonl")


@pytest.fixture(scope="module")
def runs():
    return {name: lab.load_run(FIX / f"{name}.json") for name in ("ft-lora", "base", "frontier")}


@pytest.fixture(scope="module")
def costs():
    return json.loads((FIX / "costs.json").read_text())


@pytest.fixture(scope="module")
def summary(cases, runs, costs):
    return lab.summarize(cases, list(runs.values()), costs, reference="frontier")


def test_every_non_reference_row_has_per_field_differences(summary):
    for name in ("ft-lora", "base"):
        per_field = summary["rows"][name]["fields_vs_reference"]
        assert set(per_field) == set(lab.FIELDS), f"{name}: one entry per field"
        for f, v in per_field.items():
            assert set(v) == {"diff", "lower", "upper"}
            assert v["lower"] <= v["diff"] <= v["upper"], f"{name} {f}: the estimate sits inside its interval"
    assert "fields_vs_reference" not in summary["rows"]["frontier"], "the reference is not compared with itself"


def test_per_field_differences_are_paired_on_the_same_cases(cases, runs, summary):
    ft = lab.score_run(cases, runs["ft-lora"])
    fr = lab.score_run(cases, runs["frontier"])
    for f in lab.FIELDS:
        expected = lab.paired_bootstrap_diff([s["fields"][f] for s in ft], [s["fields"][f] for s in fr], seed=0)
        assert summary["rows"]["ft-lora"]["fields_vs_reference"][f] == expected, f"reuse paired_bootstrap_diff for {f}"


def test_per_field_numbers_match_the_headline_story(summary):
    ft = summary["rows"]["ft-lora"]["fields_vs_reference"]
    assert round(ft["priority"]["diff"], 4) == round(10 / 150, 4), "the adapter is ahead on priority"
    assert round(ft["owner"]["diff"], 4) == round(-5 / 150, 4), "and behind on owners"
    assert ft["priority"]["lower"] < 0 < ft["priority"]["upper"], "but neither field difference excludes zero"


def test_report_lists_each_field_difference(summary):
    md = lab.render_report(summary)
    assert re.search(r"^- ft-lora vs frontier, priority: \+6\.7 points \[[+-]\d+\.\d, \+\d+\.\d\]", md, re.M)
    assert re.search(r"^- ft-lora vs frontier, owner: -3\.3 points", md, re.M)
    for name in ("ft-lora", "base"):
        for f in lab.FIELDS:
            assert re.search(rf"^- {re.escape(name)} vs frontier, {f}: [+-]\d+\.\d points", md, re.M), (name, f)
    assert "frontier vs frontier" not in md


def test_existing_report_content_is_unchanged(summary):
    md = lab.render_report(summary)
    assert re.search(r"^- ft-lora vs frontier: \+7\.3 points \[[+-]\d+\.\d, \+\d+\.\d\]", md, re.M)
    assert summary["rows"]["ft-lora"]["vs_reference"]["diff"] == pytest.approx(11 / 150)
    assert md.rstrip().endswith("traffic that differs from the test set."), "the caveat stays the closing line"
