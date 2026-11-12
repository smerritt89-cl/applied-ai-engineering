"""Lab e1: helpers for training a tiny character-level GPT.

Fill in the TODOs. The tests in test_tiny_gpt.py import from this file and run offline,
without PyTorch. train_outline.py uses these helpers once you've written them.
"""
from __future__ import annotations

import math
import random
import re

_START = re.compile(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*\*\*\*", re.IGNORECASE)
_END = re.compile(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*\*\*\*", re.IGNORECASE)


def strip_gutenberg(text: str) -> str:
    """Return only the body of a Project Gutenberg plain-text file.

    Keep the text strictly between the "*** START OF ... ***" and "*** END OF ... ***" marker
    lines (use the _START and _END patterns above), stripped of surrounding whitespace.
    If either marker is missing, or END comes before START, raise ValueError rather than guessing.
    """
    # TODO
    raise NotImplementedError


class CharTokenizer:
    """A character-level tokenizer: one id per distinct character, ids assigned in sorted order."""

    def __init__(self, chars: list[str]):
        self.itos = list(chars)
        self.stoi = {ch: i for i, ch in enumerate(self.itos)}

    @classmethod
    def from_text(cls, text: str) -> "CharTokenizer":
        """TODO: build the vocabulary from the sorted set of characters in text.
        Raise ValueError for empty text."""
        raise NotImplementedError

    @property
    def vocab_size(self) -> int:
        return len(self.itos)

    def encode(self, s: str) -> list[int]:
        """TODO: map each character to its id. Raise ValueError (not KeyError) for a character
        outside the vocabulary, naming the character."""
        raise NotImplementedError

    def decode(self, ids: list[int]) -> str:
        """TODO: map ids back to characters and join them."""
        raise NotImplementedError


def train_val_split(ids: list[int], val_fraction: float = 0.1) -> tuple[list[int], list[int]]:
    """TODO: contiguous split. The first int((1 - val_fraction) * len(ids)) ids are train, the rest val.
    Raise ValueError unless 0 < val_fraction < 1."""
    raise NotImplementedError


def get_batch(
    data: list[int], block_size: int, batch_size: int, rng: random.Random
) -> tuple[list[list[int]], list[list[int]]]:
    """TODO: sample batch_size start positions with rng.randrange(len(data) - block_size).
    For each start i, x = data[i : i + block_size] and y = data[i + 1 : i + block_size + 1].
    Raise ValueError if len(data) <= block_size. Return (xs, ys)."""
    raise NotImplementedError


def stable_softmax(logits: list[float], temperature: float = 1.0) -> list[float]:
    """TODO: softmax(logits / temperature). Subtract the max before exponentiating.
    Raise ValueError if temperature <= 0."""
    raise NotImplementedError


def uniform_loss(vocab_size: int) -> float:
    """TODO: the cross-entropy of a uniform model over vocab_size tokens."""
    raise NotImplementedError
