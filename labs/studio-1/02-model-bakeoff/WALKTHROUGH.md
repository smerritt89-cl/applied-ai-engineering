# Walkthrough: a model bake-off harness

## What this code does

`solution.py` runs the same prompts through two or more models and turns the results into a
decision. For every (prompt, model) pair it records the output, the tokens, the latency, the
cost, and any error. It gives each output a crude automatic score, summarizes each model
(mean score, errors, cost per task, p50 and p95 latency), picks the cheapest model that clears
your quality bar, and writes everything to a CSV so you can score the outputs by hand and
re-summarize without calling any API again.

The file reads top to bottom in three parts. First, **provided plumbing**: the price table, two
small data classes, one adapter per provider API, and a function that finds which providers you
have keys for. Second, **the harness** (the part you'd write on the write track): running,
scoring, summarizing, picking, and writing the CSV. Third, **provided tooling**: reading your
hand-scored CSV back in, printing the table, and the command line.

The design idea worth taking away: **a failure is data, not a crash.** If one model times out
on one prompt in eight, that is a finding about the model, so the harness records it and keeps
going. And the decision rule is code (`pick_winner`), so anyone can see exactly why a model won.

## How to read this lab

Open `work.py` beside this page. It starts as a copy of `solution.py`, so the line numbers
below match it until you change something. Read a section here, then the code it points to.
The harness functions (lines 150 to 249) deserve the closest reading; the adapters and command
line can be skimmed.

Run the tests from VS Code's **Testing** panel (the flask icon): expand
`studio-1/02-model-bakeoff` and press the run button. Everything except the one `live` test
runs without an API key. To see a test fail on purpose, change `>=` to `>` on line 224, rerun,
read the message, and undo it.

## Imports, prices, and defaults (lines 1 to 33)

```python
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

HERE = pathlib.Path(__file__).parent

PRICES: dict[str, dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50},
    ...
}

DEFAULT_CLAUDE_MODELS = ["claude-sonnet-5-5", "claude-haiku-5-5"]
OPTIONAL_MODELS = {"openai": "gpt-6.1-sol", "gemini": "gemini-3.8-flash", "xai": "grok-4.3"}
```

The imports are all from Python's standard library: `argparse` for the command line, `csv` and
`json` for files, `math` for rounding up, `pathlib` for file paths, `time` for timing. `HERE`
(line 14) is the folder this file lives in, so `prompts.json` and `results.csv` are found
regardless of which folder you run the script from.

`PRICES` (lines 22 to 30) holds only input and output prices, a simplification compared with
Lab 01 (no cache pricing, since this harness sends no cached prompts). The comment block above
it (lines 16 to 21) dates the snapshot, links each provider's pricing page, and records the
conditions the numbers depend on (Gemini Flash rates through a date, xAI rates below a prompt
size). Those conditions are exactly what an AI-generated price table tends to leave out.

`DEFAULT_CLAUDE_MODELS` (line 32) is a list; `OPTIONAL_MODELS` (line 33) maps a provider to the
one model id used for it. Keeping model ids as named constants at the top means there is one
place to update when providers rename models, which they do often.

## `Candidate` and `Result` (lines 36 to 56)

```python
@dataclass
class Candidate:
    provider: str
    model: str
    call: Callable[[str, int], tuple[str, int, int, str]]


@dataclass
class Result:
    prompt_id: str
    provider: str
    model: str
    output: str = ""
    input_tokens: int = 0
    ...
    error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
```

`@dataclass` is a **decorator** (a line starting with `@` that modifies the definition below
it). It turns a class that only lists fields with type hints into a full data class: Python
writes the constructor, a readable printout, and equality comparison for you. So
`Result("p1", "anthropic", "small")` works, with every other field taking its default.

`Candidate` is one model you can call. Its `call` field holds a **function**, typed as
`Callable[[str, int], tuple[str, int, int, str]]`: it takes a prompt and a max-token limit and
returns a tuple of (text, input tokens, output tokens, stop reason). Every provider's adapter
returns that same shape, which is what lets the harness treat Claude, OpenAI, Gemini, and Grok
identically. It's also what makes testing easy: the tests build a `Candidate` whose `call` is a
tiny fake function.

`Result` is one (prompt, model) run. Every field after the first three has a default, so a
failed run can be created with just its identifiers and an `error`. Line 56,
`field(default_factory=dict)`, gives each `Result` its **own** empty dictionary. Writing
`extra: dict = {}` instead would be a classic Python bug (a mutable default shared by every
instance), and dataclasses refuse it with an error for that reason.

## The provider adapters (lines 63 to 108)

```python
def claude_caller(client: Any, model: str) -> Callable[[str, int], tuple[str, int, int, str]]:
    def call(prompt: str, max_tokens: int):
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}]
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return text, resp.usage.input_tokens, resp.usage.output_tokens, resp.stop_reason

    return call
```

Each adapter is a function that **returns a function**. `claude_caller(client, model)` defines
`call` inside itself and returns it. The inner `call` still has access to `client` and `model`
after the outer function has finished; that is called a **closure**. The result is a function
with the uniform `(prompt, max_tokens)` shape, with the provider details baked in.

`claude_caller` (lines 63 to 73) uses the official `anthropic` SDK. Line 70 joins only the text
blocks, by `type`, never by position, so a thinking block in front of the answer is skipped
rather than crashing the call.

`openai_responses_caller` (lines 76 to 90) serves both OpenAI and xAI, since its docstring
notes xAI documents the same endpoint shape. It reads usage with
`int(getattr(usage, "input_tokens", 0) or 0)`, which tolerates a missing usage object, a
missing field, and a `None` value. `openai_chat_caller` (lines 93 to 108) handles Gemini's
OpenAI-compatible endpoint and, per its docstring, deliberately does not send `max_tokens`.

Note that the three adapters return different things in the "stop reason" slot: Claude's
`stop_reason`, the Responses API's `status`, and Chat Completions' `finish_reason`. The CSV
records whatever the provider said, but the harness never compares these values across
providers, which is right, because they are different vocabularies. The README's advice
applies: these are minimal adapters, so read each provider's docs before extending one.

## `available_candidates` (lines 111 to 140)

```python
def available_candidates(env: dict[str, str] | None = None, claude_models: list[str] | None = None) -> list[Candidate]:
    env = dict(os.environ) if env is None else env
    out: list[Candidate] = []
    if env.get("ANTHROPIC_API_KEY"):
        import anthropic
        ...
    try:
        from openai import OpenAI  # optional dependency: pip install openai
    except ImportError:
        OpenAI = None  # noqa: N806
```

This builds the list of models to run, based on which API keys are present. Two design choices
make it safe and testable.

First, `env` is a parameter (line 111). Normally it is a copy of the real environment (line
114), but a test can pass `env={}` and confirm that no keys means an empty list, not an error.
That test runs on any machine, with or without keys.

Second, the imports are **inside** the function (lines 117 and 123), not at the top of the file.
`openai` is optional, so importing it at the top would crash the whole file for anyone who
hasn't installed it. The `try` / `except ImportError` block (lines 122 to 125) turns "package
not installed" into "skip these providers". Missing keys and missing packages are both treated
as "not available", which the docstring states plainly.

`claude_models or DEFAULT_CLAUDE_MODELS` (line 120) uses `or` to fall back to the defaults when
`claude_models` is `None` or an empty list. Each key is read only from `env` and passed to its
client; nothing here prints or logs a key.

## `load_prompts` (lines 143 to 144)

```python
def load_prompts(path: pathlib.Path = HERE / "prompts.json") -> list[dict[str, Any]]:
    return json.loads(path.read_text())
```

`HERE / "prompts.json"` uses `pathlib`'s `/` operator to join path parts, which works on every
operating system. `path.read_text()` reads the whole file as a string and `json.loads` parses
it into a list of dictionaries, each with an `id`, a `prompt`, and optionally `must_include`.

## `cost_usd` (lines 150 to 152)

```python
def cost_usd(model: str, input_tokens: int, output_tokens: int, prices=PRICES) -> float:
    p = prices[model]
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000
```

Price per million tokens, times tokens, divided by a million. `prices[model]` with square
brackets raises `KeyError` for an unknown model on purpose: a bake-off that silently prices a
mistyped model at zero would make that model look like the obvious winner. Passing `prices` as
a parameter with a default lets a test (or you) try a different price table without editing
the constant.

## `run_one` (lines 155 to 174)

```python
    r = Result(prompt_id=prompt_row["id"], provider=candidate.provider, model=candidate.model)
    start = clock()
    try:
        text, tin, tout, stop = candidate.call(prompt_row["prompt"], max_tokens)
    except Exception as exc:  # noqa: BLE001 (a failure is a data point, not a crash)
        r.latency_s = clock() - start
        r.error = f"{type(exc).__name__}: {exc}"
        return r
    r.latency_s = clock() - start
    r.output, r.input_tokens, r.output_tokens, r.stop_reason = text, tin, tout, stop
    r.cost_usd = cost_usd(candidate.model, tin, tout, prices)
    return r
```

This runs one prompt on one model. The signature (lines 155 to 162) uses a bare `*` so that
`max_tokens`, `clock`, and `prices` must be passed by name. `clock` defaults to
`time.perf_counter` (a timer meant for measuring durations), and the tests pass a fake clock
that advances 1.5 seconds per call, so latency is checked exactly.

The `Result` is created first (line 163) with only its identifiers, then filled in. Line 166
uses **tuple unpacking**: the adapter returns four values, and `text, tin, tout, stop = ...`
assigns them to four names in one step.

The `try` / `except Exception` block is the heart of "a failure is data". Any exception from
the call (a timeout, a rate limit, a provider outage) is caught, and the result records the
latency up to the failure (line 168) and an error string (line 169) built with an **f-string**:
`type(exc).__name__` is the exception's class name, so a timeout becomes
`"TimeoutError: simulated timeout"`. The output stays empty and the cost stays 0.

Catching every exception is normally a red flag. Here it is deliberate and documented by the
comment, because the job of this function is to measure, and a crash would throw away every
result gathered so far. Compare Lab 01's `with_retries`, which catches broadly but re-raises
anything it can't handle; the right choice depends on what the function is for.

Two things to notice as a reviewer. This harness does **not** retry: a transient error counts
against the model, which is a choice you could argue either way, but it is visible. And it
records `stop_reason` but doesn't act on it, so a truncated answer is scored like any other
(see the review questions).

## `run_bakeoff` (lines 177 to 178)

```python
def run_bakeoff(candidates: list[Candidate], prompts: list[dict[str, Any]], **kwargs: Any) -> list[Result]:
    return [run_one(c, p, **kwargs) for p in prompts for c in candidates]
```

A **list comprehension with two `for` clauses** reads like nested loops, outer first: for each
prompt, for each candidate. So the order is prompt-major: p1 on every model, then p2 on every
model. The test `test_run_bakeoff_runs_every_pair_in_prompt_major_order` pins that down.

`**kwargs` collects any extra keyword arguments (such as `max_tokens=2048` or a fake `clock`)
into a dictionary, and `**kwargs` in the call passes them straight through to `run_one`. So
`run_bakeoff` doesn't need to know or repeat `run_one`'s options.

Prompt-major order has a practical benefit: if the run is interrupted halfway, you have every
model's answer to the first prompts, rather than one model's answers to everything.

## `auto_score` (lines 181 to 188)

```python
def auto_score(result: Result, must_include: list[str]) -> float:
    if result.error:
        return 0.0
    if not must_include:
        return 1.0
    text = result.output.lower()
    hits = sum(1 for term in must_include if term.lower() in text)
    return hits / len(must_include)
```

The score is the fraction of required terms that appear in the output, ignoring case. `if
result.error:` relies on **truthiness**: an empty string is false, any non-empty string is true.
So a failed run scores 0. A prompt with no required terms scores 1.0, which also avoids dividing
by zero on the last line.

`sum(1 for term in must_include if ...)` is a **generator expression** that yields a 1 for every
term found, so `sum` counts them. Both sides are lowercased, so `"GROUP by"` matches
`"group BY"`.

The README is blunt about this, and it bears repeating: this is a keyword check, not a quality
judgment. "Total 48 features" contains `"48"` whether or not 48 is the right answer to the
question. It catches gross failures (empty output, wrong topic). The CSV's `human_score`
column exists because the auto-score can't be trusted on its own.

## `percentile` (lines 191 to 196)

```python
def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[k - 1]
```

This is the **nearest-rank** percentile: sort the values, then take the one at rank
`ceil(p / 100 x n)`. For the 20 values 1 to 20, p95 is rank `ceil(19.0) = 19`, which is the
value 19. `math.ceil` rounds up. `max(1, ...)` keeps the rank at least 1, so p0 returns the
smallest value instead of indexing position -1 (which in Python would wrap to the *last* item,
a silent bug). The `k - 1` converts a 1-based rank into a 0-based list index.

An empty list returns `None` rather than 0, because "no successful calls" and "zero seconds"
are different facts. Nearest-rank always returns one of the actual measurements, never an
interpolated value between two, which is easy to explain. With eight prompts, though, p95 is
simply the slowest call, so treat it as a rough signal.

## `summarize` (lines 199 to 219)

```python
    by_model: dict[str, list[Result]] = {}
    for r in results:
        by_model.setdefault(r.model, []).append(r)
    summary: dict[str, dict[str, Any]] = {}
    for model, rs in by_model.items():
        ok = [r for r in rs if not r.error]
        lat = [r.latency_s for r in ok]
        total_cost = sum(r.cost_usd for r in rs)
        summary[model] = {
            ...
            "mean_score": sum(scores.get((r.prompt_id, model), 0.0) for r in rs) / len(rs),
            ...
        }
```

Lines 200 to 202 **group** the results by model. `by_model.setdefault(r.model, [])` returns the
list already stored for that model, or stores and returns a new empty list if there isn't one
yet; `.append(r)` then adds the result to it. It's a compact way to build a dict of lists.

`scores` is a dictionary keyed by a **tuple** `(prompt_id, model)`. Tuples can be dictionary
keys because they can't be changed; lists can't be. Keeping scores separate from results is
what lets the same `summarize` work with auto-scores during a run and with your hand scores
after `--rescore`.

Then, per model (lines 204 to 218): `ok` is the successful runs only. Latency percentiles
(lines 215 and 216) and mean output tokens (line 217) use only `ok`, because a timed-out call's
latency measures the timeout, not the model. But the mean score (line 212) divides by **all**
runs, with a missing score counting as 0 via `scores.get(..., 0.0)`, so errors drag the mean
down. That's the right asymmetry: a model shouldn't look fast because its slow calls failed,
and it shouldn't look accurate because its hard prompts errored out.

One subtlety to notice in review: `cost_per_task_usd` (line 214) is total cost divided by all
runs, and failed runs cost 0 here. So a model that errors often shows a *lower* cost per task.
`pick_winner` excludes any model with errors, so this can't pick a flaky winner, but the
printed table can flatter a flaky model.

## `pick_winner` (lines 222 to 227)

```python
def pick_winner(summary: dict[str, dict[str, Any]], quality_bar: float) -> str | None:
    passing = [(s["cost_per_task_usd"], s["p95_latency_s"] or float("inf"), m)
               for m, s in summary.items() if s["mean_score"] >= quality_bar and s["errors"] == 0]
    if not passing:
        return None
    return min(passing)[2]
```

This is the decision rule in four lines. The list comprehension keeps models that clear the
quality bar **and** had zero errors, and for each builds a tuple of (cost, p95 latency, name).

`min(passing)` relies on how Python compares **tuples**: element by element, left to right. So
the lowest cost wins; if two costs are exactly equal, the lower p95 wins; if those tie too, the
alphabetically first name wins. `[2]` then takes the name out of the winning tuple. A tie-break
rule expressed as tuple order is compact, but you have to know the trick to read it, so it is
worth a comment if you write one yourself.

`s["p95_latency_s"] or float("inf")` replaces a missing p95 (`None`) with infinity, so a model
with no latency data loses every tie. `float("inf")` is Python's positive infinity, larger than
any number.

Returning `None` when nothing passes (lines 225 and 226) is an honest answer: "no model met
your bar" is a result, and it tells you to improve the prompt or try a stronger tier rather
than ship the least bad option.

## `CSV_COLUMNS` and `write_csv` (lines 230 to 249)

```python
    rows = sorted(results, key=lambda r: (r.prompt_id, r.model))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            d = asdict(r)
            w.writerow({
                **{k: d[k] for k in CSV_COLUMNS if k in d},
                "auto_score": round(scores.get((r.prompt_id, r.model), 0.0), 3),
                "human_score": "",
                "latency_s": round(r.latency_s, 3),
                "cost_usd": f"{r.cost_usd:.6f}",
            })
```

`CSV_COLUMNS` (lines 230 to 233) fixes the column order. Note that `extra` is not in it, so it
never reaches the file.

`sorted(..., key=lambda r: (r.prompt_id, r.model))` (line 237) sorts by prompt, then model.
The `key=` argument is a function that says what to sort *by*; a **lambda** is a one-line
unnamed function. Grouping by prompt puts the models' answers to the same question next to
each other, which is what you want when scoring by hand.

`with open(path, "w", newline="") as f:` opens the file inside a **context manager**, so it is
closed even if an error happens partway. `newline=""` is what Python's `csv` documentation asks
for, so the `csv` module controls line endings itself. `csv.DictWriter` writes dictionaries as
rows and handles **quoting**: an output containing commas or newlines is wrapped in quotes so it
stays in one cell. Building CSV lines with string joins instead (a common AI shortcut) breaks
the first time a model writes a comma, and the round-trip test feeds it exactly that:
`"line one\nline, two"`.

Line 242, `asdict(r)`, converts the dataclass into a plain dictionary. Lines 243 to 249 build
each row by **dictionary unpacking**: `**{...}` copies the matching fields in, then the keys
written after it override four of them with formatted values. In a dict literal, later keys
win. The auto-score is rounded to 3 places, latency to 3, cost is written with exactly 6
decimals, and `human_score` is left empty for you to fill in.

## `load_scores_from_csv` (lines 255 to 269)

```python
            raw = row["human_score"].strip() or row["auto_score"]
            scores[(r.prompt_id, r.model)] = float(raw)
```

This reads a results CSV back into `Result` objects and a scores dictionary, so `--rescore`
can re-summarize without any API calls. CSV cells are always strings, so each number is
converted with `int(...)` or `float(...)`, and `or 0` handles empty cells
(`int(row["input_tokens"] or 0)`).

Line 267 is the important one: `row["human_score"].strip() or row["auto_score"]`. If you
filled in a human score, it wins; if the cell is empty (or only spaces, which `.strip()`
removes), the auto-score is used. That lets you hand-score only the rows you've read and still
get a summary.

## `print_summary` and `main` (lines 272 to 316)

`print_summary` (lines 272 to 280) prints one line per model, sorted by mean score, highest
first: `key=lambda kv: -kv[1]["mean_score"]` sorts on the negated score, a common trick for
descending order. A missing p95 prints as `-`. It ends by naming the winner from `pick_winner`.

`main` (lines 283 to 306) wires up the command line with `argparse`: `--models`, `--out`,
`--bar` (the quality bar, default 0.8), and `--rescore`. With `--rescore` it reads your CSV
and returns early (lines 291 to 294), never touching an API. Otherwise it finds candidates,
exits with a clear message if there are none (line 298), runs the bake-off, scores it, writes
the CSV, prints the total cost, and prints the summary.

Line 302 builds a lookup from prompt id to its required terms with a **dict comprehension**,
and `p.get("must_include", [])` treats a prompt without the field as having no required terms.

The `if __name__ == "__main__":` block (lines 309 to 316) runs only when you execute the file
directly. It loads `labs/.env` if `python-dotenv` is installed, then calls `main()`.

## What the tests check

**Pricing (2 tests).** `cost_usd` on Haiku and Sonnet, and `KeyError` for an unknown model.
A sanity check on the whole price table: every price is positive and no model's output is
cheaper than its input, which catches swapped columns.

**Running (3 tests).** With fake candidates and a fake clock: a successful run records output,
tokens, stop reason, latency (1.5 s), and cost. A failing run records an error string that
starts with the exception type, zero cost, empty output, and its latency. `run_bakeoff` runs
every pair in prompt-major order.

**Scoring and aggregation (6 tests).** `auto_score`: full and partial matches,
case-insensitivity, errors scoring 0, and no required terms scoring 1. `percentile`: empty,
single value, p50, p95, p100, and p0 on unsorted input. `summarize` on a three-model fixture:
counts, mean score, total and per-task cost, p50 and p95, mean output tokens, errors counted as
0 in the mean, and latency taken from successful calls only. A missing score counts as 0.
`pick_winner`: the cheapest passing model wins, a higher bar changes the winner, a model with
errors never wins, and cost ties break on p95.

**CSV (1 test).** A round trip: column order, sort order, a value with a comma and a newline
surviving intact, rounding and formatting, the empty `human_score`, and then a hand-filled
human score overriding the auto-score on reload.

**Setup (2 tests).** `prompts.json` has at least five prompts with unique ids and the right
shape, and no keys means no candidates rather than an error.

**Live (1 test, needs a key).** Two Claude tiers on one real prompt, with no errors and nonzero
tokens and cost.

**What they don't check.** The provider adapters' parsing (only the live test touches a real
SDK, and only Claude's), what happens to a truncated answer, `print_summary`'s output, the
`main` command line, a CSV with a malformed number, and whether the auto-score agrees with a
human. That last gap is the subject of Studio 3.

## Review questions

1. `run_one` catches every exception. In Lab 01, `with_retries` also catches every exception but
   re-raises most of them. Why is "catch and record" right here?

   <details><summary>Answer</summary>

   The two functions have different jobs. `with_retries` exists to make a call succeed, so any
   error it can't fix must reach the caller. `run_one` exists to measure a model, and a failure
   is a measurement: "this model timed out on prompt p4" belongs in the results. Crashing would
   throw away every result already collected. The catch is safe because the error isn't
   hidden: it is recorded with its type and message, scored as 0, and excludes the model from
   winning.

   </details>

2. An AI changes line 212 to average the score over `ok` (the successful runs) instead of `rs`
   (all runs), saying "failed calls shouldn't count against quality". What changes in
   `test_summarize_stats`, and in a real decision?

   <details><summary>Answer</summary>

   The `flaky` model's mean score goes from 0.5 to 1.0, so the test's "errors count as 0 in the
   mean" assertion fails. In a real bake-off, a model that fails on the hardest prompts would
   look *more* accurate than one that attempts them all. `pick_winner` would still exclude it
   for having errors, but the printed table would mislead anyone reading it.

   </details>

3. A model hits `max_tokens` on two of eight prompts, and its truncated answers happen to contain
   the required keywords. How does the harness treat those rows, and what would you change?

   <details><summary>Answer</summary>

   As normal successes: `stop_reason` is recorded in the CSV but never checked, so the rows get
   full auto-scores and count toward the win. Options: score a Claude `max_tokens` stop as 0 or
   flag it in the summary, raise `max_tokens` for the run, and check the `stop_reason` column
   while hand-scoring. Because the adapters report different stop-reason vocabularies per
   provider, a check like this has to be written per provider, not as one string comparison.

   </details>

4. Why does `percentile` use `max(1, ...)` instead of just `math.ceil(p / 100 * len(ordered))`?

   <details><summary>Answer</summary>

   For `p = 0`, the rank would be 0, and `ordered[0 - 1]` is `ordered[-1]`, which in Python is the
   **last** item: p0 would silently return the maximum. `max(1, ...)` makes the smallest rank 1,
   so p0 returns the minimum. The test `percentile([5.0, 1.0, 3.0], 0) == 1.0` guards it.

   </details>

5. Two models clear the bar with exactly the same cost per task. Which does `pick_winner` choose,
   and how would you know from reading the code?

   <details><summary>Answer</summary>

   The one with the lower p95 latency, because `min` compares the tuples element by element:
   cost first, then p95, then name. If p95 also ties, the alphabetically first model name wins,
   which is arbitrary. You know it only by recognizing the tuple-comparison idiom; the code has
   no comment saying so, which is a fair thing to ask for in review.

   </details>
