"""Offline tests for the e1 tiny-GPT lab helpers. No API key, no GPU, and no PyTorch required.

Run:  pytest electives/e1-tiny-gpt -q

The last tests compare your softmax and batching with PyTorch's. They run only if torch is
installed (pip install torch) and are skipped otherwise.
"""
from __future__ import annotations

import math
import random

import pytest

import starter as lab

GUTENBERG_SAMPLE = """The Project Gutenberg eBook of A Tiny Example

This eBook is for the use of anyone anywhere in the United States...

*** START OF THE PROJECT GUTENBERG EBOOK A TINY EXAMPLE ***

CHAPTER I.

It was a quiet morning. Nobody spoke.

*** END OF THE PROJECT GUTENBERG EBOOK A TINY EXAMPLE ***

Updated editions will replace the previous one...
"""

TEXT = "First Citizen:\nBefore we proceed any further, hear me speak.\n\nAll:\nSpeak, speak.\n"


# ---------------------------------------------------------------- corpus cleaning


def test_strip_gutenberg_keeps_only_the_body():
    body = lab.strip_gutenberg(GUTENBERG_SAMPLE)
    assert body.startswith("CHAPTER I.")
    assert body.endswith("Nobody spoke.")
    assert "Project Gutenberg" not in body, "the license header and footer must be removed"


def test_strip_gutenberg_accepts_older_this_marker():
    old = GUTENBERG_SAMPLE.replace("START OF THE", "START OF THIS").replace("END OF THE", "END OF THIS")
    assert lab.strip_gutenberg(old).startswith("CHAPTER I.")


def test_strip_gutenberg_refuses_to_guess():
    with pytest.raises(ValueError):
        lab.strip_gutenberg("Just some text with no markers.")


# ---------------------------------------------------------------- tokenizer


def test_vocab_is_sorted_unique_characters():
    tok = lab.CharTokenizer.from_text(TEXT)
    assert tok.itos == sorted(set(TEXT))
    assert tok.vocab_size == len(set(TEXT))
    assert tok.stoi["\n"] == 0, "newline sorts first among these characters"


def test_round_trip():
    tok = lab.CharTokenizer.from_text(TEXT)
    for s in [TEXT, "speak", "", "\n\n"]:
        ids = tok.encode(s)
        assert all(isinstance(i, int) and 0 <= i < tok.vocab_size for i in ids)
        assert tok.decode(ids) == s


def test_round_trip_non_ascii():
    text = "café naïve, 東京 😀"
    tok = lab.CharTokenizer.from_text(text)
    assert tok.decode(tok.encode(text)) == text
    assert len(tok.encode("😀")) == 1, "a character tokenizer gives one id per code point"


def test_unknown_character_is_a_clear_error():
    tok = lab.CharTokenizer.from_text("abc")
    with pytest.raises(ValueError, match="z"):
        tok.encode("abz")


def test_empty_text_has_no_vocabulary():
    with pytest.raises(ValueError):
        lab.CharTokenizer.from_text("")


# ---------------------------------------------------------------- split and batches


def test_split_is_contiguous_and_complete():
    ids = list(range(100))
    train, val = lab.train_val_split(ids, 0.1)
    assert train == list(range(90)) and val == list(range(90, 100))
    assert train + val == ids, "no ids are lost or duplicated"


def test_split_rejects_bad_fraction():
    for bad in (0, 1, -0.1, 1.5):
        with pytest.raises(ValueError):
            lab.train_val_split(list(range(10)), bad)


def test_batch_targets_are_inputs_shifted_by_one():
    data = list(range(50))
    xs, ys = lab.get_batch(data, block_size=8, batch_size=16, rng=random.Random(0))
    assert len(xs) == len(ys) == 16
    for x, y in zip(xs, ys):
        assert len(x) == len(y) == 8
        assert x[1:] == y[:-1], "y is x shifted left by one position"
        start = x[0]
        assert x == data[start : start + 8] and y[-1] == data[start + 8], "windows must be contiguous slices of data"


def test_batches_are_reproducible_with_a_seed():
    data = list(range(1000))
    a = lab.get_batch(data, 16, 4, random.Random(123))
    b = lab.get_batch(data, 16, 4, random.Random(123))
    assert a == b


def test_batch_never_reads_past_the_end():
    data = list(range(10))
    for seed in range(50):
        xs, ys = lab.get_batch(data, block_size=9, batch_size=3, rng=random.Random(seed))
        assert all(y[-1] == 9 for y in ys), "with block_size 9 on 10 tokens, the only window is the whole sequence"


def test_batch_rejects_data_too_short():
    with pytest.raises(ValueError):
        lab.get_batch(list(range(8)), block_size=8, batch_size=1, rng=random.Random(0))


# ---------------------------------------------------------------- softmax and baseline


def test_softmax_is_a_distribution():
    p = lab.stable_softmax([2.0, 1.0, 0.1])
    assert abs(sum(p) - 1) < 1e-12
    assert p[0] > p[1] > p[2]


def test_softmax_is_shift_invariant_and_stable():
    a = lab.stable_softmax([1.0, 2.0, 3.0])
    b = lab.stable_softmax([1001.0, 1002.0, 1003.0])
    assert all(abs(x - y) < 1e-12 for x, y in zip(a, b)), "naive exp(1003) overflows; subtract the max"


def test_softmax_temperature():
    cold = lab.stable_softmax([2.0, 1.0, 0.1], temperature=0.05)
    hot = lab.stable_softmax([2.0, 1.0, 0.1], temperature=100.0)
    assert cold[0] > 0.999
    assert max(hot) - min(hot) < 0.01
    with pytest.raises(ValueError):
        lab.stable_softmax([1.0], temperature=0.0)


def test_uniform_loss_is_the_baseline():
    assert abs(lab.uniform_loss(65) - math.log(65)) < 1e-12
    assert abs(lab.uniform_loss(27) - 3.295836866004329) < 1e-12


# ---------------------------------------------------------------- optional: agree with PyTorch


def test_softmax_matches_torch():
    torch = pytest.importorskip("torch")
    rng = random.Random(0)
    logits = [rng.uniform(-20, 20) for _ in range(50)]
    ours = lab.stable_softmax(logits, temperature=0.7)
    ref = torch.softmax(torch.tensor(logits, dtype=torch.float64) / 0.7, dim=0).tolist()
    assert all(abs(a - b) < 1e-12 for a, b in zip(ours, ref))


def test_uniform_loss_matches_torch_cross_entropy():
    torch = pytest.importorskip("torch")
    logits = torch.zeros(4, 65, dtype=torch.float64)
    targets = torch.tensor([0, 10, 20, 64])
    ref = torch.nn.functional.cross_entropy(logits, targets).item()
    assert abs(lab.uniform_loss(65) - ref) < 1e-12
