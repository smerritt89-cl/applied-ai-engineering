"""Reference solution for the e1 tiny-GPT lab helpers. Try starter.py first.

These are the pure-Python pieces around a character-level GPT: cleaning a Project Gutenberg
text, a character tokenizer, a train/val split, batching, a stable softmax, and the
uniform-model baseline loss. None of them needs PyTorch.
"""
from __future__ import annotations

import math
import random
import re

_START = re.compile(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*\*\*\*", re.IGNORECASE)
_END = re.compile(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*\*\*\*", re.IGNORECASE)


def strip_gutenberg(text: str) -> str:
    """Return only the body of a Project Gutenberg plain-text file.

    Keeps the text strictly between the "*** START OF ... ***" and "*** END OF ... ***" marker
    lines, stripped of surrounding whitespace. If either marker is missing, raise ValueError
    rather than guessing, so you notice files that need manual cleaning.
    """
    start = _START.search(text)
    end = _END.search(text)
    if not start or not end or end.start() < start.end():
        raise ValueError("Project Gutenberg START/END markers not found; clean this file by hand")
    return text[start.end() : end.start()].strip()


class CharTokenizer:
    """A character-level tokenizer: one id per distinct character, ids assigned in sorted order."""

    def __init__(self, chars: list[str]):
        self.itos = list(chars)
        self.stoi = {ch: i for i, ch in enumerate(self.itos)}

    @classmethod
    def from_text(cls, text: str) -> "CharTokenizer":
        if not text:
            raise ValueError("cannot build a vocabulary from empty text")
        return cls(sorted(set(text)))

    @property
    def vocab_size(self) -> int:
        return len(self.itos)

    def encode(self, s: str) -> list[int]:
        try:
            return [self.stoi[ch] for ch in s]
        except KeyError as err:
            raise ValueError(f"character {err.args[0]!r} is not in the vocabulary") from None

    def decode(self, ids: list[int]) -> str:
        return "".join(self.itos[i] for i in ids)


def train_val_split(ids: list[int], val_fraction: float = 0.1) -> tuple[list[int], list[int]]:
    """Contiguous split: the first (1 - val_fraction) of the sequence is train, the rest is val.

    A contiguous split (as in the lecture) keeps validation text from overlapping training text.
    """
    if not 0 < val_fraction < 1:
        raise ValueError("val_fraction must be strictly between 0 and 1")
    n = int((1 - val_fraction) * len(ids))
    return ids[:n], ids[n:]


def get_batch(
    data: list[int], block_size: int, batch_size: int, rng: random.Random
) -> tuple[list[list[int]], list[list[int]]]:
    """Sample batch_size random chunks. x is data[i : i + block_size], y is the same window shifted by one."""
    if len(data) <= block_size:
        raise ValueError("data must be longer than block_size")
    starts = [rng.randrange(len(data) - block_size) for _ in range(batch_size)]
    xs = [data[i : i + block_size] for i in starts]
    ys = [data[i + 1 : i + block_size + 1] for i in starts]
    return xs, ys


def stable_softmax(logits: list[float], temperature: float = 1.0) -> list[float]:
    """softmax(logits / temperature), subtracting the max first so large logits don't overflow."""
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    scaled = [z / temperature for z in logits]
    m = max(scaled)
    exps = [math.exp(z - m) for z in scaled]
    total = sum(exps)
    return [e / total for e in exps]


def uniform_loss(vocab_size: int) -> float:
    """Cross-entropy of a model that assigns equal probability to every token: log(vocab_size)."""
    return math.log(vocab_size)
