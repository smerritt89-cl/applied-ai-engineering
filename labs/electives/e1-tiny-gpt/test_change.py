"""Acceptance tests for CHANGE.md: add a top_k option to stable_softmax.

Run:  pytest electives/e1-tiny-gpt/test_change.py -q

They fail until the change is made in work.py, and are skipped in a full run of the lab.
Offline: no API key, no PyTorch.
"""
from __future__ import annotations

import math
import random

import pytest

import starter as lab

pytestmark = pytest.mark.change

LOGITS = [2.0, 1.0, 0.1, -1.0]


def test_default_is_unchanged():
    assert lab.stable_softmax(LOGITS, top_k=None) == lab.stable_softmax(LOGITS)
    assert lab.stable_softmax(LOGITS, temperature=0.7, top_k=None) == lab.stable_softmax(LOGITS, temperature=0.7)


def test_top_k_zeroes_everything_outside_the_top_k():
    p = lab.stable_softmax(LOGITS, top_k=2)
    assert p[2] == 0.0 and p[3] == 0.0, "logits below the k-th largest get probability exactly 0"
    assert abs(sum(p) - 1) < 1e-12, "the kept entries are renormalized to sum to 1"
    assert abs(p[0] / p[1] - math.e) < 1e-9, "the kept entries keep their relative odds"


def test_top_k_one_is_greedy():
    p = lab.stable_softmax(LOGITS, top_k=1)
    assert p == [1.0, 0.0, 0.0, 0.0]


def test_top_k_combines_with_temperature():
    p = lab.stable_softmax(LOGITS, temperature=0.5, top_k=2)
    assert p[2] == 0.0 and p[3] == 0.0
    assert abs(p[0] / p[1] - math.exp(2.0)) < 1e-9, "temperature still scales the logits that are kept"


def test_ties_at_the_threshold_are_all_kept():
    p = lab.stable_softmax([1.0, 1.0, 0.0], top_k=1)
    assert p == [0.5, 0.5, 0.0], "entries tied with the k-th largest are kept, not broken arbitrarily"


def test_top_k_at_or_above_vocab_size_changes_nothing():
    full = lab.stable_softmax(LOGITS)
    for k in (4, 5, 100):
        assert lab.stable_softmax(LOGITS, top_k=k) == full


def test_top_k_is_still_stable_with_large_logits():
    p = lab.stable_softmax([1001.0, 1002.0, 1003.0], top_k=2)
    q = lab.stable_softmax([1.0, 2.0, 3.0], top_k=2)
    assert all(abs(a - b) < 1e-12 for a, b in zip(p, q))
    assert p[0] == 0.0


def test_top_k_matches_a_reference_on_random_logits():
    rng = random.Random(0)
    logits = [rng.uniform(-20, 20) for _ in range(50)]
    k = 7
    p = lab.stable_softmax(logits, temperature=0.8, top_k=k)
    keep = sorted(range(50), key=lambda i: logits[i], reverse=True)[:k]
    exps = {i: math.exp((logits[i] - max(logits)) / 0.8) for i in keep}
    total = sum(exps.values())
    for i in range(50):
        expected = exps[i] / total if i in exps else 0.0
        assert abs(p[i] - expected) < 1e-12


def test_bad_top_k_is_rejected():
    for bad in (0, -1):
        with pytest.raises(ValueError):
            lab.stable_softmax(LOGITS, top_k=bad)
