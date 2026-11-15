# Walkthrough: the tiny-GPT data helpers

## What this code does

`solution.py` holds everything around a character-level GPT except the model itself: the steps that turn a raw text file into training batches, plus two numerical helpers. Read top to bottom, it is the data pipeline in order. It strips a Project Gutenberg file down to the book, builds a character tokenizer, splits the token ids into training and validation sets, cuts random batches out of them, and provides a stable softmax with temperature and the baseline loss your model must beat.

None of it needs PyTorch, and every function is small and pure (same input, same output, no hidden state), except that `get_batch` takes its randomness as an argument. That is what makes the pipeline testable offline. It is also where most silent bugs in a training project live: a model trained on badly cleaned text, a leaky split, or targets shifted the wrong way still trains, still produces a falling loss curve, and is still wrong.

The math is light but load-bearing. The model is trained to estimate P(next character | previous characters), the loss is cross-entropy measured in nats, and the uniform model's loss, log V, is the reference point for every number you will log.

## How to read this lab

Open `work.py` in VS Code beside this page. It starts as a copy of `solution.py` (made by `python lab.py review`), so the line numbers below match it until you edit it. Each section names a function and its line range, quotes the key lines, and explains them.

Run the tests from VS Code's **Testing** panel (the flask icon). With `work.py` present, `test_tiny_gpt.py` runs against it, and everything should pass. The two tests that compare with PyTorch are skipped unless torch is installed.

## Module header and imports (lines 1 to 11)

```python
from __future__ import annotations

import math
import random
import re
```

The docstring says what the module is for and what it doesn't need (PyTorch), which tells a reader the scope at a glance.

`from __future__ import annotations` makes Python treat type hints as text that isn't evaluated when the function is defined. It lets hints such as `-> "CharTokenizer"` or `int | None` work consistently across Python versions. It changes nothing about how the code runs.

The three imports are all from the standard library: `math` for `log` and `exp`, `random` for the batch sampler's generator type, and `re` for regular expressions. When reviewing an AI-written version of a module like this, an unexpected import (numpy, torch, requests) is a quick sign it is doing more than you asked.

## The Gutenberg marker patterns (lines 13 to 14)

```python
_START = re.compile(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*\*\*\*", re.IGNORECASE)
```

`re.compile` builds a regular expression once, at import time, so `strip_gutenberg` doesn't rebuild it on every call. The leading underscore marks these as internal to the module.

Reading the pattern piece by piece:

- `r"..."` is a **raw string**, so backslashes reach the regex engine unchanged.
- `\*\*\*` matches three literal asterisks (a bare `*` means "repeat" in a regex, so it must be escaped).
- `\s*` allows any amount of whitespace.
- `(?:THE|THIS)` is a **non-capturing group** matching either word. Newer Gutenberg files say "THE", older ones say "THIS", and a test covers both.
- `[^\n]*` matches the rest of the line (the book's title), anything except a newline, so a match can never run onto the next line.
- `re.IGNORECASE` tolerates capitalization differences.

Patterns like this are easy for an AI to get almost right. The common failure is a pattern that is too loose (for example `.*` without the newline restriction, which with some flags can swallow text) or too strict (only "THE"). The tests pin down the two real variants.

## `strip_gutenberg` (lines 17 to 28)

```python
start = _START.search(text)
end = _END.search(text)
if not start or not end or end.start() < start.end():
    raise ValueError("Project Gutenberg START/END markers not found; clean this file by hand")
return text[start.end() : end.start()].strip()
```

`search` returns a **match object** if the pattern occurs anywhere, or `None` if it doesn't. A match object knows where it matched: `start.end()` is the index just after the START line, and `end.start()` is the index where the END line begins. The **slice** `text[a : b]` takes exactly the characters in between, and `.strip()` removes leading and trailing whitespace.

The design decision is in the `if` on line 26: if either marker is missing, or END comes before START, the function raises `ValueError` instead of returning something. The docstring states the reason: guessing would quietly train your model on a license header or a truncated book. A loud failure costs you a minute; a silent one costs you a training run and a confusing result. When an AI writes a cleaning function, check what it does on input it doesn't recognize. "Return the text unchanged" is the tempting and wrong answer here.

`if not start` works because `None` counts as false in a condition. Python's `or` short-circuits, so `end.start()` is only evaluated once both matches are known to exist.

## `CharTokenizer` (lines 31 to 55)

This class is the tokenizer: a fixed mapping between characters and integer ids. Its job is to be a bijection on its vocabulary, so that `decode(encode(s)) == s` for any string made of known characters.

### The constructor (lines 34 to 36)

```python
def __init__(self, chars: list[str]):
    self.itos = list(chars)
    self.stoi = {ch: i for i, ch in enumerate(self.itos)}
```

`itos` ("integer to string") is a list where position i holds character i. `stoi` is the reverse map, built with a **dict comprehension**; `enumerate` yields `(index, item)` pairs. `list(chars)` copies the input so that a caller who later changes their own list can't change the tokenizer.

The type hint `chars: list[str]` documents that this expects a list of single characters. Hints are not enforced at runtime; they are for readers and editors.

### `from_text`, an alternative constructor (lines 38 to 42)

```python
@classmethod
def from_text(cls, text: str) -> "CharTokenizer":
    if not text:
        raise ValueError("cannot build a vocabulary from empty text")
    return cls(sorted(set(text)))
```

`@classmethod` is a **decorator** that makes the method receive the class itself (`cls`) instead of an instance. It's the standard way to offer a second constructor: `CharTokenizer.from_text(book)` reads more clearly than computing the vocabulary yourself and calling `CharTokenizer(...)`. `cls(...)` then calls the normal constructor.

`sorted(set(text))` keeps each distinct character once and puts them in code-point order. Sorting is what makes ids reproducible: a set has no guaranteed order, so building from an unsorted set could assign different ids on different runs, and a saved model would then decode to gibberish. The test checks that newline sorts first (code point 10 comes before space, 32).

Empty text raises an error rather than producing a tokenizer with no vocabulary, which would fail later in a less obvious place.

### `vocab_size` (lines 44 to 46)

```python
@property
def vocab_size(self) -> int:
    return len(self.itos)
```

`@property` lets you read a computed value like an attribute: `tok.vocab_size`, with no parentheses. Computing it from `itos` means it can never disagree with the actual vocabulary, which a separately stored number could.

V, the vocabulary size, sets the size of the model's output layer and the baseline loss log V.

### `encode` (lines 48 to 52)

```python
try:
    return [self.stoi[ch] for ch in s]
except KeyError as err:
    raise ValueError(f"character {err.args[0]!r} is not in the vocabulary") from None
```

The list comprehension looks each character up. A character that isn't in the vocabulary makes the dict lookup raise `KeyError`, and the **try/except** turns that into a `ValueError` whose message names the character.

Details worth knowing:

- `err.args[0]` is the missing key, here the character.
- `!r` in the **f-string** formats it with `repr`, so a tab or newline shows up as `'\t'` or `'\n'` rather than as invisible whitespace.
- `from None` hides the original `KeyError` from the traceback, so the reader sees one clear error instead of two chained ones.

Why convert the error at all: `KeyError: 'z'` from deep inside a comprehension doesn't tell the caller what went wrong, while "character 'z' is not in the vocabulary" does. And callers can catch one documented exception type. A common AI shortcut is `self.stoi.get(ch, 0)`, which silently maps unknown characters to id 0. That would corrupt text without any error, and the test `test_unknown_character_is_a_clear_error` exists to rule it out.

### `decode` (lines 54 to 55)

```python
def decode(self, ids: list[int]) -> str:
    return "".join(self.itos[i] for i in ids)
```

A **generator expression** looks up each id, and `"".join(...)` concatenates the characters into one string. `join` on a list of strings is the efficient way to build a string in Python; repeated `+` would copy the string every time.

One thing to notice in review: `decode` doesn't validate its input. An id that is too large raises `IndexError`, which is reasonable, but a **negative** id such as `-1` silently returns the last character in the vocabulary, because negative indices count from the end of a Python list. Model output is always in range, so this is acceptable here, but it's the kind of edge a reviewer should be able to state.

## `train_val_split` (lines 58 to 66)

```python
if not 0 < val_fraction < 1:
    raise ValueError("val_fraction must be strictly between 0 and 1")
n = int((1 - val_fraction) * len(ids))
return ids[:n], ids[n:]
```

`0 < val_fraction < 1` is a **chained comparison**, Python's way of writing a double inequality. Fractions of 0 or 1 would leave one split empty, which would crash or mislead later, so they are rejected up front.

`int(...)` truncates toward zero, so with 100 ids and a fraction of 0.1, n is 90. The two slices `ids[:n]` and `ids[n:]` cover every id exactly once, which the test checks with `train + val == ids`.

The important decision is **contiguous** rather than random. Training examples are overlapping windows of the text. If you shuffled positions before splitting, nearly every validation window would overlap a training window by all but a few characters, and validation loss would measure memorization, not generalization. Taking the last 10% as one block keeps the two sets apart, at the cost that the validation text may differ in style from the rest (the end of a book is not the middle). If an AI suggests "shuffle before splitting for a fairer sample", that's the leakage the lab README warns about.

## `get_batch` (lines 69 to 78)

```python
if len(data) <= block_size:
    raise ValueError("data must be longer than block_size")
starts = [rng.randrange(len(data) - block_size) for _ in range(batch_size)]
xs = [data[i : i + block_size] for i in starts]
ys = [data[i + 1 : i + block_size + 1] for i in starts]
return xs, ys
```

The signature spreads over several lines (lines 69 to 71) because it has type hints for four arguments and a return value. `tuple[list[list[int]], list[list[int]]]` says: a pair of batches, each a list of id lists.

Each batch element is a window of `block_size` ids starting at a random position, and its target is the same window shifted one position right. So `ys[b][t]` is the id that follows `xs[b][t]`. This is how one window gives `block_size` training examples at once: at position t the model sees `x[0..t]` and must predict `y[t]`, and the causal mask in attention ensures it can't peek further.

The bounds are the delicate part. `rng.randrange(n)` returns an integer from 0 to n - 1, so the largest start is `len(data) - block_size - 1`, and the last target index is then `len(data) - 1`, the final id. One more and that window's `ys` would come up a token short; one fewer and the last token could never appear as a target. Off-by-one errors in this line are among the most common bugs in AI-written batching code, and Python slicing makes them silent: a slice past the end just returns a shorter list instead of raising an error.

The test `test_batch_never_reads_past_the_end` uses 10 ids with `block_size=9`, where exactly one valid window exists, and catches the gross versions of this bug (such as `rng.randrange(len(data))`). Be aware that it does **not** catch the subtle one: with `len(data) - block_size + 1`, the extra start position produces a short target whose last id is still 9, so the test passes, and the shifted-by-one test only fails if its random draws happen to hit that one bad start. With the current seeds they don't. That gap was found while writing this walkthrough, and `test_every_window_is_full_length` now closes it: it checks that every window has exactly `block_size` tokens, over 50 seeds in the one-window case, so the bad start is certain to be drawn. This is a good example of why you read the tests, not just their pass count (see review question 2).

`rng` is passed in rather than using the global `random` module. That makes batches reproducible from a seed (tested) and lets `train_outline.py` control the randomness of the whole run.

## `stable_softmax` (lines 81 to 89)

```python
scaled = [z / temperature for z in logits]
m = max(scaled)
exps = [math.exp(z - m) for z in scaled]
total = sum(exps)
return [e / total for e in exps]
```

Softmax maps logits z to probabilities exp(z_i) / sum_j exp(z_j). Dividing by a temperature T first sharpens the distribution (T below 1) or flattens it (T above 1).

Subtracting the maximum before exponentiating relies on shift invariance: softmax(z) = softmax(z - c) for any constant c, because the factor exp(-c) cancels between numerator and denominator. Choosing c = max(z) makes the largest exponent exp(0) = 1, so nothing overflows (`math.exp(1003)` would raise `OverflowError`) and the denominator is at least 1. The test with logits 1001 to 1003 checks both stability and that the answer equals the unshifted one.

Temperature must be positive: at 0 the division fails, and a negative value would invert the ranking. The function raises `ValueError` instead. The limits are worth knowing: as T approaches 0 the distribution approaches all probability on the maximum (greedy decoding), and as T grows it approaches uniform. The temperature test checks both ends.

## `uniform_loss` (lines 92 to 94)

```python
def uniform_loss(vocab_size: int) -> float:
    return math.log(vocab_size)
```

A model that gives every token probability 1/V has cross-entropy minus log(1/V) = log V on every example, whatever the data. For the 65-character Tiny Shakespeare vocabulary that is about 4.17 nats.

It's one line, but it is the most useful number in the project. A freshly initialized model's logits should be near zero, so its first loss should be near log V. Much higher means the output layer starts out confidently wrong; much lower before any training suggests leakage. The optional PyTorch test confirms that `torch.nn.functional.cross_entropy` on all-zero logits gives the same value, which ties this function to the framework you will train with.

## What the tests check

`test_tiny_gpt.py` groups its tests by pipeline stage.

- **Corpus cleaning** (3 tests): only the body survives, with the license header and footer gone; the older "THIS" marker works; text without markers raises `ValueError` instead of being returned.
- **Tokenizer** (5 tests): the vocabulary is the sorted unique characters and `vocab_size` matches it; round trips work for ASCII, empty strings, newlines, accented letters, CJK characters, and an emoji (one id per code point); unknown characters raise a `ValueError` that names the character; empty text raises.
- **Split and batches** (6 tests): the split is contiguous and loses nothing; bad fractions are rejected; targets are inputs shifted by one and windows are contiguous slices of the data; a seed makes batches reproducible; batches never read past the end; data no longer than `block_size` is rejected.
- **Softmax and baseline** (4 tests): the output is a distribution in the right order; shifting by 1000 changes nothing and doesn't overflow; extreme temperatures behave as expected and 0 is rejected; `uniform_loss` is log V.
- **Optional PyTorch agreement** (2 tests): your softmax matches `torch.softmax` on random logits, and `uniform_loss` matches `cross_entropy` on all-zero logits. Skipped without torch.

What they don't cover: the subtle off-by-one in `get_batch` described above (the suite passes with it), real Gutenberg files (formats vary more than the two marker variants), very large inputs and speed, negative ids passed to `decode`, a fraction like 0.1 on very short sequences (where the validation split could be tiny), and anything about the model or the training loop in `train_outline.py`. The first time you run on your own book, read the `--check-data` output by eye; it's the test the suite can't write for you.

## Review questions

1. An AI assistant changes `encode` to `return [self.stoi.get(ch, 0) for ch in s]`, saying it "avoids crashes on unexpected characters". What breaks, and which test catches it?

<details>
<summary>Answer</summary>

Unknown characters are silently mapped to id 0, which is a real character (newline, in the test text). `decode(encode(s))` no longer returns `s` for such strings, and nothing reports it. `test_unknown_character_is_a_clear_error` fails because no `ValueError` is raised. If you genuinely need to handle unseen characters, the right fix is an explicit unknown token added to the vocabulary, not reusing an existing id.

</details>

2. In `get_batch`, an AI changes `rng.randrange(len(data) - block_size)` to `rng.randrange(len(data) - block_size + 1)`. What goes wrong, and how often?

<details>
<summary>Answer</summary>

The largest start becomes `len(data) - block_size`, so for that start the target slice `data[i + 1 : i + block_size + 1]` runs one past the end, and Python returns a list one element short instead of raising an error. It happens only when that one start is drawn, so on a large corpus it's rare and intermittent; in `train_outline.py`, `torch.tensor` would then fail on the ragged batch at some unpredictable step.

And the original tests didn't catch it. In the one-window test the short target still ends in 9, so `y[-1] == 9` holds, and the other batch tests don't happen to draw the bad start with their seeds. All 18 of the original offline tests passed. The fix was a test that checks `len(y) == block_size` for a case where the bad start is certain to be drawn (10 ids, `block_size=9`, many seeds); the lab now has it as `test_every_window_is_full_length`. Reviewing AI code means asking "would a test fail if this line were wrong?", not only "do the tests pass?"

</details>

3. Why is the train/validation split contiguous rather than a random sample of positions?

<details>
<summary>Answer</summary>

Training examples are overlapping windows. With a random split, almost every validation window would share all but a few characters with some training window, so validation loss would reward memorization and look far better than the model's real ability to continue unseen text. A contiguous split keeps the sets disjoint. The cost is that the held-out block may not be representative of the whole text, which is worth noting when you interpret the gap.

</details>

4. Your first logged loss is 4.9 on a corpus with 65 distinct characters. Is that a problem?

<details>
<summary>Answer</summary>

`uniform_loss(65)` is about 4.17, so 4.9 is noticeably above the uniform baseline. That means the initial model is somewhat confidently wrong, which points to the output layer's initialization being too large (lesson 5). It isn't fatal, since training will pull it down, but the first steps are spent undoing a bad start. Scaling down the final layer's initial weights should bring step 0 close to 4.17.

</details>

5. Why does `strip_gutenberg` raise an error instead of returning the text unchanged when it can't find the markers?

<details>
<summary>Answer</summary>

Because returning the text unchanged would let a file with an unexpected format slip through, and the model would train on license boilerplate or a truncated book without any signal that something was wrong. Failing loudly forces you to look at the file. In data pipelines, a clear error is much cheaper than a silently wrong dataset.

</details>
