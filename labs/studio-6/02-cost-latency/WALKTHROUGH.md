# Walkthrough: measure a baseline, add prompt caching, compare

## What this code does

`solution.py` is a measurement harness for one question: does prompt caching make this workload
cheaper and faster, and by how much? It sends the same six support questions twice, once as a
**baseline** (no caching) and once **cached** (with a `cache_control` breakpoint after a shared
2,000-token handbook), streams every response, and records three timestamps plus the token usage
for each. Then it prices each response, summarizes each arm (cost, cache read fraction, latency
percentiles), compares them, and checks the cached arm for signs that caching silently stopped
working.

The file reads top to bottom as a pipeline, and the module docstring (lines 1 to 9) draws it:
build the request, time the call, run both arms interleaved, then analyze.

Two design ideas are worth taking away. First, **the two arms differ only by the cache marker**,
and the tests enforce that, because a comparison where anything else changed measures the wrong
thing. Second, **the analysis runs on plain recorded data** (dictionaries of numbers), so the
same code can analyze a live run, a saved run, or a synthetic fixture, and every test except one
runs offline.

## How to read this lab

Open `work.py` beside this page. It starts as a copy of `solution.py`, so the line numbers below
match it until you change something. Read a section here, then the code it points to.

Run the tests from VS Code's **Testing** panel (the flask icon): expand
`studio-6/02-cost-latency` and press the run button. Everything except the one `live` test runs
without an API key, using a fake streaming client, a fake clock, and the two JSON fixtures in
`fixtures/`. To see a test fail on purpose, add a timestamp to `INSTRUCTIONS` inside
`build_request` (for example `+ str(time.time())`), rerun, read the message, and undo it.

## Imports, constants, and prices (lines 10 to 30)

```python
from __future__ import annotations
...
MODEL = "claude-haiku-5-5"
MAX_TOKENS = 4000
HERE = pathlib.Path(__file__).parent
...
PRICES_CHECKED_ON = "2026-11-11"
PRICES = {
    "claude-opus-5-5": {"input": 4.00, "cache_write_5m": 5.00, "cache_write_1h": 8.00, "cache_read": 0.20, "output": 20.00},
    ...
}
```

- `from __future__ import annotations` (line 10) lets the file use newer **type hint** syntax
  such as `list[dict]` on older Python versions. Hints (`usage: dict`, `-> float`) document what
  functions take and return; they don't change behavior.
- `HERE` is the folder this file lives in (`__file__` is this file's path, `.parent` its folder),
  so `samples/` and `fixtures/` are found no matter where you run the script from.
- `PRICES` is a **nested dictionary**: model id, then five rates in dollars per million tokens.
  `PRICES_CHECKED_ON` records the snapshot date as data, not just a comment, so a report could
  print it. Prices change; code that hard-codes them should always say when they were checked.
- Notice the ratios on every row: a 5-minute cache write is 1.25 times input, a 1-hour write 2
  times, a read one twentieth (one tenth on Haiku), and output five times input.

## The workload (lines 32 to 43)

`INSTRUCTIONS` is the system prompt, a **triple-quoted string** that spans several lines.
`QUESTIONS` are six realistic support questions, each answerable from the handbook. Keeping the
workload in the file makes the experiment reproducible: anyone can rerun exactly the same
requests.

## `request_cost` (lines 49 to 63)

```python
p = prices[model]
writes = usage.get("cache_creation_input_tokens", 0) or 0
breakdown = usage.get("cache_creation") or {}
w1h = breakdown.get("ephemeral_1h_input_tokens", 0) or 0
w5m = writes - w1h
```

The same pricing logic as the week 2 in-browser exercise. It multiplies each of the four meters
by its rate and divides by a million.

- `prices[model]` uses square brackets, so an unknown model raises `KeyError`. That is
  deliberate: a missing price must fail loudly, never cost $0. A test checks it.
- `.get(key, 0) or 0` handles both a missing key and a key whose value is `None` (the
  `test_cost_treats_missing_meters_as_zero` test passes `None` on purpose).
- Cache writes are split into 1-hour and 5-minute writes using the optional `cache_creation`
  breakdown. Without a breakdown, every write is priced as a 5-minute write.
- `1_000_000` uses underscores as digit separators, for readability only.

## `total_input` (lines 66 to 72)

The prompt size is the sum of three input meters: uncached input, cache writes, and cache reads.
This matters because with caching on, `input_tokens` alone is tiny (only the part after the
breakpoint), so it badly understates how big the prompt really is. `cache_health` and the cache
read fraction both depend on this total.

## `percentile` (lines 78 to 84)

Nearest-rank percentile, as in lesson 6: sort, take the value at rank ceil(p/100 times n),
counting from 1. `sorted` makes a sorted copy, so the caller's list isn't reordered. `max(k, 1)`
guards against a rank of 0, which would index `-1` (Python's "last item") and silently return the
maximum.

## `build_request` (lines 90 to 101)

```python
doc_block = {"type": "text", "text": f"<handbook>\n{document}\n</handbook>"}
if cached:
    doc_block["cache_control"] = {"type": "ephemeral"}
return {
    "model": model,
    "max_tokens": MAX_TOKENS,
    "output_config": {"effort": "low"},
    "system": [{"type": "text", "text": INSTRUCTIONS}, doc_block],
    "messages": [{"role": "user", "content": question}],
}
```

Builds the keyword arguments for `client.messages.stream()`, as a plain dictionary.

- The `*` in the signature makes `cached` **keyword-only**: callers must write `cached=True`,
  which reads clearly and can't be confused with another positional argument.
- The system prompt is a **list of two text blocks**: the instructions, then the handbook wrapped
  in tags with an **f-string**. The cache breakpoint goes on the second block, so everything up to
  and including the handbook is the cached prefix, and the question (in `messages`) comes after
  it.
- The only difference between the arms is the `if cached:` line. Everything else, including
  `output_config` (a request setting this lab keeps fixed at low effort for both arms), is
  identical.

Why it is built this way: a cache only hits when the prefix is **byte-identical** to a previous
request. Anything that varies per request (a timestamp, a user name, a request id) must come after
the breakpoint, or every request writes a fresh cache and none ever reads. Two tests check this
directly: the arms differ only by the marker, and the system prefix is the same across questions.

**Reviewing AI-written versions:** look for anything dynamic before the breakpoint (dates, ids,
shuffled lists, a dictionary serialized in a varying order), and for sampling parameters
(`temperature`) added to one arm only. The lab has a test that no sampling parameters are set.

## `usage_to_dict` (lines 104 to 120)

```python
get = (lambda k: usage.get(k)) if isinstance(usage, dict) else (lambda k: getattr(usage, k, None))
```

The SDK returns usage as an object with attributes; the fixtures store it as a dictionary. This
function accepts either and returns a plain dictionary of numbers.

- Line 106 picks one of two small **lambdas** (one-line unnamed functions) with a **conditional
  expression**, then uses `get("input_tokens")` the same way regardless of the input's type.
  `getattr(obj, name, None)` reads an attribute that may not exist without crashing.
- `or 0` turns a missing or `None` meter into 0.
- The breakdown (lines 113 to 119) is copied only if present, using the same trick.

Why: a record you can `json.dumps` can be logged, saved, and replayed through the analysis later.
One test calls `json.dumps(rec)` for exactly that reason.

## `timed_call` (lines 123 to 147)

```python
sent = clock()
ttft = first_text = None
with client.messages.stream(**params) as stream:
    for event in stream:
        now = clock() - sent
        if event.type == "message_start" and ttft is None:
            ttft = now
        elif (
            event.type == "content_block_delta"
            and getattr(event.delta, "type", None) == "text_delta"
            and first_text is None
        ):
            first_text = now
    message = stream.get_final_message()
total = clock() - sent
```

Streams one request and records three moments, in seconds after sending.

- `clock=time.perf_counter` is a **default argument** holding a function. `perf_counter` is a
  high-resolution clock meant for measuring short durations. Tests pass a fake clock instead, so
  the expected times are exact.
- `ttft = first_text = None` is a **chained assignment**: both start as `None`.
- `client.messages.stream(**params)` **unpacks** the request dictionary into keyword arguments.
  The `with ... as stream:` block is a **context manager**: it guarantees the streaming connection
  is closed when the block ends, even if an error happens.
- **Time to first token** is when `message_start` arrives. **Time to first text** is the first
  `content_block_delta` whose delta is a `text_delta`. The README explains why these differ: Haiku
  5.5 thinks first by default, and thinking arrives as other delta types. The `is None` checks
  make sure only the *first* occurrence is recorded.
- `stream.get_final_message()` returns the complete message, including usage, once the stream
  ends. **Total time** is measured after it returns.
- The return value (lines 140 to 147) is a plain dictionary: model, three times, stop reason, and
  normalized usage.

**Reviewing AI-written versions:** check where the timestamps are taken. Measuring "first token"
after the loop, or treating any delta as first text, gives numbers that look plausible and mean
something else. The fake stream in the tests puts a `thinking_delta` before the first
`text_delta` to catch the second mistake.

## `run_comparison` (lines 150 to 162)

```python
for r in range(rounds):
    for i, q in enumerate(questions):
        arms = ("baseline", "cached") if order % 2 == 0 else ("cached", "baseline")
        order += 1
        for arm in arms:
            rec = timed_call(client, build_request(document, q, cached=(arm == "cached")), clock=clock)
            rec.update({"arm": arm, "question_index": i, "round": r})
            records.append(rec)
```

Runs both arms on the same questions, **interleaved**, and alternates which arm goes first.

- `enumerate(questions)` yields each question with its index.
- `order % 2 == 0` (the remainder after dividing by 2) flips the order on every question:
  baseline then cached, cached then baseline, and so on.
- `rec.update({...})` adds the labels to the record dictionary in place.

Why interleave: service latency drifts over minutes. If you ran all baseline requests and then
all cached ones, any drift would show up as a difference between the arms. Alternating also
spreads any advantage of going first (or second) evenly across both arms. This is the same idea
as a randomized, paired experiment design.

## `summarize` (lines 168 to 188)

```python
costs = [request_cost(r["usage"], r["model"]) for r in records]
reads = sum(r["usage"].get("cache_read_input_tokens", 0) for r in records)
inputs = sum(total_input(r["usage"]) for r in records)

def pcts(key):
    vals = [r[key] for r in records if r.get(key) is not None]
    return {"p50": percentile(vals, 50), "p95": percentile(vals, 95)} if vals else {"p50": None, "p95": None}
```

One arm's summary: count, total and mean cost, the fraction of input tokens read from cache, and
p50 and p95 of each of the three timings.

- A **list comprehension** prices every record; **generator expressions** inside `sum()` add up
  the read and total input tokens.
- `pcts` is a **nested function** used three times. It skips records with a missing timing (a
  response with no text has `first_text_s` of `None`) instead of crashing, and returns `None`
  percentiles if nothing is left.
- `reads / inputs if inputs else 0.0` avoids dividing by zero.
- It includes the first cached request, which pays the cache-write premium. The README calls
  that honest: dropping the "cold" request would overstate the savings on a low-traffic route.

## `compare` (lines 191 to 205)

Summarizes each arm and computes three ratios: cost, p50 time to first token, and p50 total time.
A ratio below 1 means the cached arm is better. The small `ratio` helper returns `None` when
either side is missing or the denominator is zero, so a report never shows a division error. On
the fixture, cost drops to about 0.54 of baseline while the time ratios stay close to 1, which is
the lab's main finding: caching cuts cost a lot more than latency on a prefix this size.

## `cache_health` (lines 208 to 224)

```python
if total_input(records[0]["usage"]) < min_prefix:
    warnings.append(...)
warm = records[1:]
if warm and all(r["usage"].get("cache_read_input_tokens", 0) == 0 for r in warm):
    warnings.append("no cache reads after the first request: look for a silent invalidator")
rewritten = [
    r for r in warm
    if total_input(r["usage"]) and r["usage"].get("cache_creation_input_tokens", 0) / total_input(r["usage"]) >= 0.5
]
```

Checks a cached arm, in time order, for three signs of trouble, and returns a list of warnings
(empty means healthy). This is the "checks and balances" step: caching can fail **silently**, and
the only evidence is in the usage meters.

- **Prompt too short** (lines 213 and 214): below the model's minimum cacheable length, the
  breakpoint is ignored.
- **No reads after the first request** (lines 215 to 217): `records[1:]` is a **slice**, every
  record after the first (the "warm" requests). `all(...)` is true only if every warm request read
  zero tokens from cache.
- **Most warm requests rewrite the cache** (lines 218 to 223): the list comprehension keeps warm
  requests where at least half the prompt was a cache write. The `total_input(...) and` part
  short-circuits on a zero total, avoiding a division by zero. If more than half the warm
  requests rewrite, the prefix is changing between requests.

The broken fixture shows both of the last two signatures at once, which is what a timestamp in the
system prompt looks like in the meters.

## Loading fixtures, the report, and the script (lines 227 to 255)

- `load_fixture` reads a JSON file from `fixtures/` into a list of dictionaries.
- `format_report` builds aligned text lines with **format specifiers** inside f-strings:
  `{arm:9s}` pads to 9 characters, `{x:.6f}` shows 6 decimal places, `{x:.0%}` shows a fraction as
  a whole percentage, and `{x:.2f}` two decimals. `s['first_text_s']['p50'] or 0` prints 0 instead
  of crashing when no text was recorded.
- `if __name__ == "__main__":` (line 247) runs only when you execute the file directly, not when
  tests import it. It imports the SDK there, so the rest of the module works without it, runs the
  live comparison, prints the report, and prints any cache warnings.

## What the tests check

- **Dollars (section 1):** each meter is priced separately; 1-hour writes use the breakdown;
  missing or `None` meters count as zero; unknown models raise; `total_input` adds three meters.
- **Percentiles (section 2):** nearest rank on an unsorted list with an outlier, and the empty case.
- **Requests (section 3):** the breakpoint sits on the handbook block only; the arms differ only by
  the marker; the system prefix is byte-identical across questions; no sampling parameters.
- **Timing (section 4):** a fake streaming client moves a fake clock to scripted times, so
  `timed_call` must report exactly 0.40, 1.80, and 2.75 seconds (and skip the thinking delta). A
  stream with no text reports `None`. `run_comparison` interleaves and alternates across questions
  and rounds, and the fake client simulates one cache write followed by reads.
- **Analysis (section 5):** exact summaries and ratios on the synthetic fixture; missing timings
  are skipped; `cache_health` passes the healthy arm and flags the broken one, a short prompt, and
  an empty list; and record order within an arm doesn't change the summary.
- **Live (section 6):** four real questions on both arms, checking that later cached requests read
  the cache and the cached arm is cheaper.

What they don't cover: whether six questions are enough to trust the latency numbers (they
aren't, for p95; the README says to treat latency ratios as a direction), the 1-hour cache
lifetime in a live run, and models other than Haiku in the live test.

## Review questions

1. Why does `build_request` put the cache breakpoint on the handbook block rather than on the user
   message?

<details>
<summary>Answer</summary>

The breakpoint marks the end of the prefix to cache. Everything before it must be identical across
requests for the cache to hit. The instructions and handbook are the same for every question; the
question is different every time. Putting the breakpoint after the question would make every
prefix unique, so every request would write a new cache entry (at a premium) and none would ever
read one.

</details>

2. An AI assistant "simplifies" `summarize` by computing the cache read fraction as
   `sum(cache_read_input_tokens) / sum(input_tokens)`. What goes wrong on the cached arm?

<details>
<summary>Answer</summary>

With caching on, `input_tokens` counts only the uncached part of the prompt (the short question),
so the denominator is tiny and the "fraction" comes out far above 1 (on the fixture, 13,580 read
tokens over 167 uncached ones, about 81). The right denominator is `total_input`: uncached input
plus cache writes plus cache reads. This is the reason `total_input` exists as its own function.

</details>

3. Why does `run_comparison` alternate which arm goes first instead of running all baseline
   requests and then all cached ones?

<details>
<summary>Answer</summary>

Service latency drifts over time. Running the arms in two blocks would mix that drift into the
comparison, so a slow minute during the cached block would look like caching made things slower.
Interleaving puts both arms under the same conditions, and alternating the order cancels out any
effect of going first.

</details>

4. The cached arm's mean cost includes the first request, which pays a cache-write premium and costs
   more than a baseline request. Is that a flaw in the measurement?

<details>
<summary>Answer</summary>

No, it is the honest number. Every cache has to be written before it can be read, and on a
low-traffic route the cache may expire between requests, so writes happen again. Dropping the
cold request would report the best case, not the real cost. If you want both views, report the
warm-only mean separately and label it as such.

</details>

5. `cache_health` returns `[]` for a run. What does that prove, and what doesn't it?

<details>
<summary>Answer</summary>

It shows the prompt was long enough to cache, later requests did read from the cache, and most
warm requests weren't rewriting it. It doesn't prove the cache is used *efficiently* (for example,
that the breakpoint is in the best place), that the answers are good, or that the latency
improved. It checks the specific ways caching silently breaks, which is what you want as a
standing check in CI.

</details>
