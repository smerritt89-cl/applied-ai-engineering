"""Acceptance tests for CHANGE.md: a json_field_max_words check type.

Run on their own, once you've made the change in work.py:
    pytest studio-1/03-prompt-test-harness/test_change.py -q
"""
import json
import pathlib

import pytest

HERE = pathlib.Path(__file__).parent

# Every lab has a module named `starter`. Import THIS lab's copy now, while this
# folder is first on sys.path; importing inside a fixture would pick up whichever
# lab's `starter` pytest collected last.
import sys as _sys

_sys.path.insert(0, str(HERE))
for _mod in ("starter", "solution"):
    _sys.modules.pop(_mod, None)
import starter as _starter  # noqa: E402  (the learner's file)

pytestmark = pytest.mark.change

CHECK = {"type": "json_field_max_words", "field": "summary", "value": 5}


def _out(**fields):
    return json.dumps({"category": "bug", "urgency": "low", **fields})


def test_short_summary_passes():
    assert _starter.run_check(CHECK, _out(summary="PDF export cuts lines.")) is True


def test_exactly_the_limit_passes():
    assert _starter.run_check(CHECK, _out(summary="one two three four five")) is True


def test_one_word_over_the_limit_fails():
    assert _starter.run_check(CHECK, _out(summary="one two three four five six")) is False


def test_words_are_split_on_any_whitespace():
    assert _starter.run_check(CHECK, _out(summary="one  two\nthree\tfour five")) is True


def test_fenced_json_is_accepted_like_the_other_json_checks():
    fenced = "```json\n" + _out(summary="Short and fine.") + "\n```"
    assert _starter.run_check(CHECK, fenced) is True


@pytest.mark.parametrize(
    "output",
    [
        _out(),  # no summary field
        _out(summary=None),
        _out(summary=["a", "list"]),
        "Sure! The summary is short.",  # not JSON
        "[1, 2, 3]",  # JSON, but not an object
    ],
)
def test_missing_wrong_type_or_unparseable_fails(output):
    assert _starter.run_check(CHECK, output) is False


def test_other_check_types_still_work():
    assert _starter.run_check({"type": "max_length", "value": 5}, "12345") is True
    assert _starter.run_check({"type": "json_field_in", "field": "category", "values": ["bug"]}, _out()) is True
    with pytest.raises(ValueError):
        _starter.run_check({"type": "vibes"}, "anything")
