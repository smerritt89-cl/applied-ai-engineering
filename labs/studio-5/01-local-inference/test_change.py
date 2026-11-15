"""Acceptance tests for CHANGE.md (Studio 5 lab 01): thinking text and first-chunk time.

Run:  pytest studio-5/01-local-inference/test_change.py -q
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

import starter as lab

pytestmark = pytest.mark.change

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def stream_events():
    return [tuple(e) for e in json.loads((FIXTURES / "ollama_chat_stream.json").read_text())["events"]]


def final_line(**extra):
    chunk = {"message": {"role": "assistant", "content": ""}, "done": True, "eval_count": 1, "eval_duration": 1}
    chunk.update(extra)
    return json.dumps(chunk)


def test_thinking_text_is_collected_separately():
    r = lab.consume_ollama_stream(stream_events())
    assert r.thinking == "The customer wants a refund.", "thinking chunks are concatenated into r.thinking"
    assert "customer wants" not in r.text, "thinking text must not leak into the answer text"
    assert lab.extract_json(r.text) == lab.EXPECTED, "the answer text is unchanged"


def test_first_chunk_time_is_the_first_non_blank_chunk():
    r = lab.consume_ollama_stream(stream_events())
    assert r.first_chunk_s == pytest.approx(0.412), "the first chunk arrives at 0.412 s, even though it is empty"
    assert r.ttft_s == pytest.approx(0.731), "TTFT keeps its meaning: the first visible content"


def test_blank_lines_do_not_count_as_first_chunk():
    events = [
        (0.05, "   "),
        (0.10, json.dumps({"message": {"role": "assistant", "content": "", "thinking": "a"}, "done": False})),
        (0.20, json.dumps({"message": {"role": "assistant", "content": "", "thinking": "b"}, "done": False})),
        (0.30, json.dumps({"message": {"role": "assistant", "content": "{}"}, "done": False})),
        (0.40, final_line()),
    ]
    r = lab.consume_ollama_stream(events)
    assert r.first_chunk_s == pytest.approx(0.10)
    assert r.thinking == "ab"
    assert r.ttft_s == pytest.approx(0.30) and r.text == "{}"


def test_stream_without_thinking_has_empty_thinking():
    events = [
        (0.1, json.dumps({"message": {"role": "assistant", "content": "hi"}, "done": False})),
        (0.2, final_line()),
    ]
    r = lab.consume_ollama_stream(events)
    assert r.thinking == "", "no thinking chunks means an empty string, not None"
    assert r.first_chunk_s == pytest.approx(0.1) and r.ttft_s == pytest.approx(0.1)


def test_existing_errors_still_raise():
    with pytest.raises(ValueError):
        lab.consume_ollama_stream([e for e in stream_events() if '"done": true' not in e[1]])
    with pytest.raises(RuntimeError):
        lab.consume_ollama_stream([(0.1, json.dumps({"error": "boom"}))])


def test_stream_result_can_still_be_built_the_old_way():
    r = lab.StreamResult(text="x", ttft_s=None)
    assert r.final == {} and r.thinking == "" and r.first_chunk_s is None, "new fields need defaults"
