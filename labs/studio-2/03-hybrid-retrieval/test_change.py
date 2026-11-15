"""Acceptance tests for CHANGE.md (Studio 2 lab 03): an optional stop-word list for BM25.

Run:  pytest studio-2/03-hybrid-retrieval/test_change.py -q
All offline. They fail until BM25 accepts stop_words.
"""
from __future__ import annotations

import math

import pytest

import starter as lab

pytestmark = pytest.mark.change

TINY = {
    "a": "error vpn-719 vpn certificate expired",
    "b": "vpn client drops on hotel wifi",
    "c": "password reset needs a code",
    "d": "certificate certificate certificate renewal renewal policy for the vpn gateway servers",
}
STOP = {"a", "the", "for", "to", "on"}


def test_stop_words_are_not_indexed():
    idx = lab.BM25(TINY, stop_words=STOP)
    for word in STOP:
        assert word not in idx.postings, f"{word!r} is a stop word and should not be in the index"
    assert idx.postings["certificate"] == {"a": 1, "d": 3}, "other terms are indexed exactly as before"


def test_stop_words_do_not_count_toward_length():
    idx = lab.BM25(TINY, stop_words=STOP)
    assert idx.lengths == {"a": 5, "b": 5, "c": 4, "d": 9}
    assert math.isclose(idx.avgdl, (5 + 5 + 4 + 9) / 4)


def test_stop_words_are_dropped_from_queries():
    idx = lab.BM25(TINY, stop_words=STOP)
    assert idx.search("the vpn-719") == idx.search("vpn-719")
    assert math.isclose(idx.score("the certificate", "d"), idx.score("certificate", "d"))
    assert idx.search("to the") == [], "a query made only of stop words matches nothing"


def test_stop_words_are_case_insensitive():
    idx = lab.BM25(TINY, stop_words={"The", "FOR"})
    assert "the" not in idx.postings and "for" not in idx.postings
    assert idx.search("THE") == []


def test_default_behavior_is_unchanged():
    before = lab.BM25(TINY)
    empty = lab.BM25(TINY, stop_words=None)
    assert "the" in before.postings, "without a stop list, every token is indexed"
    assert empty.postings == before.postings and empty.lengths == before.lengths
    assert empty.search("vpn certificate") == before.search("vpn certificate")
    assert lab.tokenize("The VPN-719") == ["the", "vpn-719"], "tokenize itself does not drop anything"
