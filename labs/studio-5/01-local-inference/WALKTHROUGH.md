# Walkthrough: Lab 01, benchmark a local model against Claude

## What this code does

This lab measures a small open model running on your own machine and compares it with a Claude model on one
realistic task: pulling five fields (name, order id, product, issue, refund requested) out of a support ticket as
JSON. It answers two questions an engineer gets asked: "how fast is it, really?" and "is the output any good?"

The code is organized in four numbered sections, marked with comment banners. Section 1 is benchmarking math: unit
conversions, Ollama's timing fields, reading a streamed reply, and summary statistics. Section 2 parses JSON out of
messy model replies and scores it field by field. Section 3 holds the live adapters that talk to Ollama, MLX, and
Claude. Section 4 is the command-line program that ties them together.

Sections 1 and 2 are pure functions: they take data in and return data out, with no network calls. That is what
lets every test run offline against recorded fixtures. Section 3 is the only part that touches the outside world,
and it is kept thin so there is little in it that can be wrong without the tests noticing.

## How to read this lab

Open `work.py` in VS Code beside this page. It starts as a copy of `solution.py`, so the line numbers below match
it until you edit it. Read a section here, then read the same lines there.

Run the tests from VS Code's **Testing** panel (the flask icon): expand `studio-5/01-local-inference` and press the
run button. The offline tests should all pass; the Ollama, MLX, and Claude tests are skipped unless you have those
set up. From a terminal, the same thing is `pytest studio-5/01-local-inference -q` from the `labs` folder.

## Imports and setup (lines 8 to 23)

```python
from __future__ import annotations

import argparse
...
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
```

`from __future__ import annotations` lets the file use modern **type hints** (such as `int | float`, "an int or a
float") on older Python versions. Type hints are the annotations after a colon or an arrow, like
`def ns_to_s(ns: int | float) -> float`. Python does not enforce them at run time; they document what each function
expects and returns, and editors use them to catch mistakes.

Everything imported is from the standard library. The lab talks to Ollama with `urllib.request` rather than a
third-party HTTP package, and imports `anthropic` and `mlx_lm` only inside the functions that need them. That keeps
the offline tests runnable with nothing extra installed. When you review AI-written code, a new top-level import of
a heavy package is worth questioning for exactly this reason.

## The task: ticket, expected answer, schema, prompt (lines 25 to 58)

```python
HERE = pathlib.Path(__file__).parent
TICKET = (HERE / "fixtures" / "ticket.txt").read_text()
EXPECTED = {"customer_name": "Dana Okafor", ..., "refund_requested": True}
SCHEMA: dict[str, Any] = {"type": "object", "properties": {...}, "required": [...], "additionalProperties": False}
```

`pathlib.Path(__file__).parent` is the folder this file lives in, so the fixture path works no matter where you
run the script from. The `/` operator joins path pieces.

`EXPECTED` (lines 29 to 35) is the gold label: what a careful person extracts from the ticket. `SCHEMA` (lines 38
to 49) is a **JSON Schema**, a standard way to describe the shape of a JSON object. The same schema is sent to
Ollama (its `format` field) and to Claude (structured outputs), so both models are held to the same contract.
`"enum"` restricts `issue` to five values, and `"additionalProperties": False` forbids extra keys.

`build_prompt` (lines 52 to 58) builds the prompt with an **f-string**, wrapping the ticket in `<ticket>` tags so
the model can tell instructions from data. Note the prompt defines `refund_requested` precisely ("true only if the
customer asks for money back"); a vague definition is a common reason models disagree with labels.

A test checks that the schema's required keys, its properties, and `EXPECTED` all name the same five fields. That
is a cheap guard against an edit that adds a field in one place and forgets the others.

## Units and rates: `ns_to_s` and `tokens_per_second` (lines 64 to 73)

```python
def ns_to_s(ns: int | float) -> float:
    return ns / 1e9

def tokens_per_second(tokens: int, seconds: float) -> float:
    if seconds <= 0:
        raise ValueError("duration must be positive")
    return tokens / seconds
```

Ollama reports every duration in **nanoseconds** (billionths of a second), so `ns_to_s` divides by `1e9`.

`tokens_per_second` refuses a zero or negative duration with `ValueError` instead of letting Python raise
`ZeroDivisionError` or return a negative rate. Raising your own error with a clear message is better because the
caller can catch it on purpose. Worked value from Ollama's documentation: 259 tokens in 4,232,710,000 ns is
259 / 4.23271 = about 61.19 tokens per second.

## `Timing` and `parse_ollama_final` (lines 76 to 109)

```python
@dataclass
class Timing:
    load_s: float
    prefill_tokens: int
    prefill_s: float
    prefill_tps: float | None
    ...

def parse_ollama_final(chunk: dict) -> Timing:
    if not chunk.get("done"):
        raise ValueError("not a final chunk (done is not true)")
    prefill_tokens = int(chunk.get("prompt_eval_count", 0) or 0)
    ...
        prefill_tps=tokens_per_second(prefill_tokens, prefill_s) if prefill_s > 0 else None,
```

`@dataclass` is a **decorator** (the `@` line above a definition) that turns a class with typed fields into a
simple record: Python writes the constructor for you, so `Timing(load_s=..., ...)` just works and the object prints
readably. Dataclasses are the standard way to return several named values without a loose dictionary whose keys
could be misspelled.

The final chunk of an Ollama stream carries the timing fields. The function splits the request into its three
phases:

- **load**: reading the model into memory (large on a cold start, near zero when it is already loaded);
- **prefill**: processing the prompt (`prompt_eval_*`);
- **decode**: generating the reply one token at a time (`eval_*`).

`chunk.get("prompt_eval_count", 0) or 0` is belt and braces: `.get` with a default covers a missing key, and
`or 0` also covers a key that is present with the value `None`. `int(...)` makes sure counts are whole numbers.

The rates use a **conditional expression**: compute the rate if the duration is positive, otherwise `None`. A fully
cached prompt has no prefill time, and the right answer is "no rate", not a crash and not zero (zero would look
like an infinitely slow prefill).

Why this matters: the test computes the naive rate, decode tokens divided by `total_duration`, and checks that it
is less than half the true decode rate on the documented cold-start example. Dividing by the total is the most
common benchmarking mistake, because the total includes the 6.3 seconds of loading. When you review AI-written
benchmark code, check which duration each rate divides by.

## `StreamResult` and `consume_ollama_stream` (lines 112 to 147)

```python
@dataclass
class StreamResult:
    text: str
    ttft_s: float | None
    final: dict = field(default_factory=dict)

def consume_ollama_stream(events: Iterable[tuple[float, str]]) -> StreamResult:
    ...
    for t, line in events:
        if not line.strip():
            continue
        chunk = json.loads(line)
        if "error" in chunk:
            raise RuntimeError(f"Ollama error: {chunk['error']}")
        content = (chunk.get("message") or {}).get("content") or ""
        if content:
            if ttft is None:
                ttft = t
            parts.append(content)
        if chunk.get("done"):
            final = chunk
```

Ollama streams its reply as **NDJSON**: one JSON object per line, sent as soon as each piece is ready. The function
does not do any network work itself. It receives `(seconds_since_request_start, raw_line)` pairs, which is what
makes it testable with a recorded fixture: the test replays a stream with known arrival times.

`field(default_factory=dict)` gives each `StreamResult` its own empty dictionary as a default. Writing `final: dict
= {}` would be rejected by dataclasses, because a single shared mutable default is a classic Python bug.

Reading the loop:

- `if not line.strip(): continue` skips blank lines (the fixture has one at 0.97 s).
- An `"error"` chunk becomes a `RuntimeError` with Ollama's message, so a missing model fails loudly.
- `(chunk.get("message") or {}).get("content") or ""` safely digs one level into the chunk. If `message` is
  missing, `or {}` substitutes an empty dictionary, and the final `or ""` turns a missing or `None` content into an
  empty string.
- **TTFT** (time to first token) is set once, from the first chunk with non-empty content. In the fixture, the
  first chunk arrives at 0.412 s but is empty, and the second (0.455 s) is thinking only. The first visible answer
  text arrives at 0.731 s, and that is the TTFT a user experiences.
- `parts.append(content)` collects pieces, and `"".join(parts)` glues them together once at the end, which is the
  efficient way to build a string from many pieces in Python.

If no chunk with `done: true` arrives, the stream was cut off, and the function raises `ValueError` rather than
returning a partial reply that would look complete. A reviewer should check exactly this kind of "what if it ends
early" path, because the happy-path tests never exercise it.

## `summarize` (lines 150 to 167)

```python
kept = list(values[discard_first:])
...
ordered = sorted(kept)
n = len(ordered)
return {"n": n, "median": statistics.median(ordered), "p90": ordered[math.ceil(0.9 * n) - 1], ...}
```

`values[discard_first:]` is a **slice** that drops the first few runs. The first run usually includes model load
time (a **warm-up** run), so keeping it would skew every statistic. `list(...)` makes a copy so the caller's list
is never changed.

The **median** is the middle value and is not dragged around by one slow outlier the way an average is. The
**p90** (90th percentile) answers "how slow is a bad but not freak run?" This code uses the **nearest-rank**
definition: sort the values and take the one at position `ceil(0.9 * n)`, counting from 1, which is index
`ceil(0.9 * n) - 1` in Python's count-from-0 lists. Worked value: for the ten values 1 to 10, `ceil(9.0) = 9`, so
p90 is the 9th smallest, 9.0. Other percentile definitions interpolate and give slightly different numbers; what
matters is using one definition consistently and saying which.

With five runs and one discarded, p90 of four values is just the maximum. That is honest but worth knowing: tail
latency needs many runs to mean anything.

## `bandwidth_ceiling_tps` (lines 170 to 174)

```python
return bandwidth_gb_s / weights_gb
```

When a model generates one token for one user, it has to read essentially every weight from memory once. So memory
bandwidth divided by the size of the weights is an upper bound on decode speed. Worked value: a 4.9 GB file on a
machine with 614 GB/s of bandwidth cannot exceed about 125 tokens per second. This is a **sanity check** for your
measurements: if you measure faster than the ceiling, the measurement is wrong.

## Finding JSON in a reply: `_FENCE`, `_first_object`, `extract_json` (lines 179 to 228)

```python
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)

def extract_json(text: str) -> dict:
    candidates = [text.strip()]
    fence = _FENCE.search(text)
    if fence:
        candidates.append(fence.group(1).strip())
    span = _first_object(text)
    if span:
        candidates.append(span)
    for cand in candidates:
        try:
            value = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("no JSON object found in reply")
```

Models without schema-constrained decoding often wrap JSON in prose or a Markdown code fence (see
`fixtures/local_reply.txt`). `extract_json` tries three increasingly forgiving readings, in order, and returns the
first that parses to a dictionary.

`_FENCE` is a compiled **regular expression**. `(?:json)?` optionally matches the word `json` after the backticks
without capturing it; `(.*?)` captures the contents, with `?` making it **non-greedy** so it stops at the first
closing fence; `re.S` lets `.` match newlines. The leading underscore in `_FENCE` and `_first_object` is a Python
convention for "internal helper, not part of the public interface".

`_first_object` (lines 182 to 205) scans character by character, counting `{` and `}` to find the first balanced
object. Its subtle part is the `in_str` and `escaped` flags: braces inside a JSON string, like
`"use {curly} braces"`, must not count, and an escaped quote `\"` must not end the string. A simpler regex such as
`\{.*\}` would break on exactly these cases, which is why the test includes one. If the first `{` never balances,
`text.find("{", start + 1)` moves on to the next one.

`isinstance(value, dict)` rejects valid JSON that is not an object: `[1, 2, 3]` parses but is not a reply in the
expected shape.

A reviewer should notice what this tolerance costs: the more forgiving the parser, the more often a malformed reply
is quietly "rescued". That is fine for a benchmark that reports the parse result, and risky in production, where a
schema-constrained call (as the Ollama and Claude adapters use) is the better fix.

## Scoring: `_norm` and `score_fields` (lines 231 to 246)

```python
def _norm(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    return value

    per_field[name] = name in predicted and type(got) is type(want) and _norm(got) == _norm(want)
```

`" ".join(value.split())` collapses any run of spaces, tabs, or newlines to a single space, and `.casefold()` is a
thorough lowercase for comparisons. So `"Standing desk frame"` matches `"standing desk frame"`.

The scoring line is three conditions joined by `and`, which Python checks left to right and stops at the first
false one (**short-circuiting**):

1. `name in predicted`: a missing field is wrong.
2. `type(got) is type(want)`: the types must match exactly. This is why the number `1` does not count as the
   boolean `True`. It also matters because in Python `True == 1` is true, so a plain `==` would accept it.
3. `_norm(got) == _norm(want)`: compare normalized values.

`sum(per_field.values()) / len(per_field)` counts `True` as 1 and `False` as 0, giving the fraction correct.

The `local_reply.txt` fixture shows the lesson's main point: it parses, fits the schema, and still says
`refund_requested: false` when the customer asked for money back. Valid is not correct.

## The live adapters (lines 251 to 370)

These are written for you, and the offline tests do not run them, so read them for where each number comes from.

- **Defaults** (lines 251 to 254): `os.environ.get("OLLAMA_HOST_URL", ...)` lets you point at a different Ollama
  server with an environment variable, falling back to the standard local address.
- **`ollama_is_running` and `ollama_has_model`** (lines 257 to 271) call Ollama's `/api/tags` endpoint inside
  `with urllib.request.urlopen(...) as resp:`. The **`with` statement** guarantees the connection is closed even if
  something fails. Both catch connection errors and return `False`, which is how the local tests skip cleanly
  instead of failing when Ollama is not installed.
- **`stream_ollama_chat`** (lines 274 to 300) posts the chat request with `"stream": True`, `temperature` 0, and the
  schema in `format`, then records `(clock() - start, line)` for each line as it arrives. The timer starts
  **before** the request is sent, so TTFT includes queueing and load, which is what a user feels. The `clock`
  parameter defaults to `time.perf_counter` (a high-resolution timer) but can be replaced, the same
  dependency-passing pattern used throughout the course to make code testable.
- **`run_ollama`** (lines 303 to 307) chains the pieces: stream, consume, parse the final chunk, and return a small
  dictionary of results.
- **`mlx_available` and `run_mlx`** (lines 310 to 344) check for Apple silicon and the `mlx_lm` package, load the
  model once into `_MLX_CACHE` (a module-level dictionary, so repeated runs don't reload), apply the model's chat
  template, and time the first non-empty piece of streamed text. `getattr(last, "prompt_tps", None)` reads an
  attribute if it exists and returns `None` otherwise, a defensive choice when a library's response objects may
  vary between versions.
- **`run_claude`** (lines 347 to 370) streams one request with structured outputs (`output_config` with a JSON
  Schema `format`) and effort set to low. It uses `with client.messages.stream(...) as stream:` and reads
  `stream.text_stream`, timing the first visible text. Its docstring notes that Opus 5.5 always thinks first, so
  TTFT includes thinking time and `output_tokens` includes thinking tokens. After the stream, it raises if the
  stop reason is `refusal` or `max_tokens`, because either means the JSON may be missing or cut off. The `client`
  is passed in rather than created inside, so a test could pass a fake one.

## The command-line program: `_fmt`, `benchmark`, `main` (lines 376 to 447)

`benchmark` (lines 380 to 402) takes a **runner**, any function from a prompt to a result dictionary. That one
parameter is why the same function can benchmark Ollama, MLX, and Claude: `main` passes a **lambda** (a small
unnamed function) such as `lambda p: run_ollama(p, model=model)`, which fixes the model and leaves only the
prompt open.

Inside, list comprehensions collect TTFTs and decode rates, skipping missing values; the first run is discarded as
warm-up when there is more than one; and the last reply is parsed and scored inside `try`/`except ValueError`, so
an unparseable reply is reported rather than crashing the program.

`main` (lines 405 to 437) uses `argparse` to read command-line options, picks a backend (Ollama if it is running,
otherwise MLX if available, otherwise none), and runs Claude only if `--claude` was passed and an API key is set.
Claude runs are capped at three to keep the cost down. The `if __name__ == "__main__":` block (lines 440 to 447)
runs only when you execute the file directly, not when the tests import it; it loads `labs/.env` if `python-dotenv`
is installed.

## What the tests check

- **Benchmarking math** (`test_ns_to_s` through `test_bandwidth_ceiling`): unit conversion; the tokens-per-second
  formula against Ollama's documented example; rejecting a zero duration; splitting load, prefill, and decode, and
  proving that dividing by the total understates decode speed; a cached prompt with no prefill rate; refusing a
  non-final chunk; nearest-rank p90 and the warm-up discard; and the bandwidth ceiling.
- **Stream parsing** (`test_stream_*`): TTFT skips empty and thinking chunks (0.731 s, not 0.412 s); the text
  concatenates to the expected JSON; a truncated stream raises; an error chunk raises with its message; a stream
  with no content has no TTFT.
- **Reply parsing and scoring** (`test_extract_json_*`, `test_score_fields_*`): plain, fenced-with-prose, and
  bare-in-prose JSON (with braces inside strings); lists and garbage rejected; string normalization; `1` is not
  `true`; a missing field is wrong; the schema, prompt, and expected answer agree.
- **Live and local** (skipped by default): one Ollama run, one MLX run, and one Claude call scored at 80% or better.

What they don't cover: the network adapters are never run offline, so a bug in a request body (a wrong field name
in `body` or `output_config`) only shows up live. The CLI's printing is untested. And one ticket is an anecdote: the
tests prove the measurement and scoring code is right, not that any model is good at the task.

## Review questions

1. A colleague reports decode speed as `eval_count / total_duration` from the final chunk. On the documented
   cold-start example, what goes wrong?

   <details><summary>Answer</summary>

   `total_duration` includes the 6.3 seconds of model loading and the prefill time, so the rate comes out at about
   24 tokens per second instead of about 61. Decode speed must divide by `eval_duration`. The test
   `test_parse_final_chunk_separates_load_prefill_decode` checks this explicitly.

   </details>

2. Why does `consume_ollama_stream` take a list of `(time, line)` pairs instead of opening the HTTP connection
   itself?

   <details><summary>Answer</summary>

   Separating the network from the logic makes the logic testable. The tests replay a recorded stream with known
   arrival times, so TTFT can be checked exactly (0.731 s) without Ollama running. `stream_ollama_chat` does the
   network part and is the only piece that needs a live server.

   </details>

3. An AI assistant changes the scoring line to `per_field[name] = _norm(predicted.get(name)) == _norm(want)`. Which
   test fails, and why does it matter?

   <details><summary>Answer</summary>

   `test_score_fields_missing_and_wrong_type` fails, because `1 == True` is true in Python, so a reply of
   `"refund_requested": 1` would be scored correct. (A missing field still fails, since `None` does not equal the
   expected value here.) It matters because downstream code that checks `is True` would treat `1` differently, and
   the schema says the field is a boolean.

   </details>

4. Your measured decode speed on a laptop is 180 tokens per second for a 4.9 GB model, and the laptop's memory
   bandwidth is 273 GB/s. What do you conclude?

   <details><summary>Answer</summary>

   The ceiling is 273 / 4.9, about 56 tokens per second, so 180 is impossible for single-stream decoding. The
   measurement is wrong: most likely the wrong duration was used, the tokens were counted wrongly, or the model file
   is not what you think it is. Fix the measurement before comparing anything.

   </details>

5. `local_reply.txt` parses and matches the schema. Why is that not enough to call the local model good enough?

   <details><summary>Answer</summary>

   It still gets `refund_requested` wrong. A schema constrains shape, not correctness. Only scoring against labels
   tells you about accuracy, and one ticket is an anecdote: you need 20 to 50 labeled examples, with a frontier model
   in the same eval as a reference, before deciding.

   </details>
