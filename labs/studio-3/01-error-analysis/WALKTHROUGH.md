# Walkthrough: the error analysis toolkit

## What this code does

This lab turns a spreadsheet of human judgments into a ranked list of what to fix. A reviewer has read 36 support-bot traces, marked each one `pass` or `fail`, written a short note (open coding), and tagged failures with labels from a small taxonomy (axial coding). The code loads those three files, checks the annotations for mistakes, counts how often each failure mode shows up, weights the counts by severity, and writes a Markdown report.

The code never decides whether a trace passed. People do that. The code's job is bookkeeping you can trust: catch typos and contradictions in the sheet, count correctly, and rank by a rule you can explain to your team.

A second, optional part (`make_tuples` and `generate_queries`) builds synthetic test messages with Claude. It is the only part that calls an API, and the tests exercise it with a fake client.

## How to read this lab

Open `work.py` beside this page. It starts as a copy of `solution.py`, so the line numbers below match it until you edit it. Read one section here, then the matching lines there.

Run the tests from VS Code's **Testing** panel (the flask icon), or from a terminal in the `labs` folder with `pytest studio-3/01-error-analysis -q`. They should all pass before you change anything. Live tests are skipped unless you have a key in `labs/.env`.

## Module header, imports, and constants (lines 1 to 30)

```python
from __future__ import annotations

import csv
import itertools
import json
import pathlib
from collections import Counter
from dataclasses import dataclass
from typing import Callable
...
DATA_DIR = pathlib.Path(__file__).parent / "data"
TRACE_FIELDS = ("trace_id", "timestamp", "channel", "plan", "user_message", "retrieved", "bot_response")
OUTCOMES = ("pass", "fail")
```

The docstring at the top is a map of the pipeline: traces in, annotations validated, counts, priorities, report out. Read it first in any AI-written module; if the map and the code disagree, one of them is wrong.

`from __future__ import annotations` lets the file use modern **type hints** such as `str | pathlib.Path` and `tuple[str, ...]` without worrying about the Python version. Type hints are labels on inputs and outputs; Python does not enforce them at run time, but they tell you (and your editor) what each function expects.

Every import is from the standard library except `pydantic`, which the synthetic step needs. `DATA_DIR` is built from `__file__` (the path of this file), so the code finds `data/` no matter which folder you run it from. `TRACE_FIELDS` and `OUTCOMES` are **tuples** (fixed, ordered sequences) declared once at the top so the loading and validation code below can't drift apart on what a valid record looks like.

## The data types (lines 36 to 65)

```python
@dataclass(frozen=True)
class Annotation:
    trace_id: str
    outcome: str  # "pass" or "fail"
    note: str  # open code: free-text observation
    failure_modes: tuple[str, ...]  # axial codes from the taxonomy
```

`@dataclass` is a **decorator**: a line starting with `@` that modifies the class below it. A dataclass writes the boring parts of a class for you (the constructor, a readable printout, equality checks) from the list of typed fields. `frozen=True` makes instances read-only: once an `Annotation` exists, nothing can quietly change its outcome. That matters in an analysis pipeline, where a function that "just fixes up" a record in place would change the numbers every later step sees.

There are three record types, one per stage: `Trace` (what the bot did), `Annotation` (what a person said about it), and `Priority` (one row of the ranked table). `retrieved` and `failure_modes` are tuples, not lists, because a frozen record should hold frozen contents; the tests check this.

`AnnotationError` (lines 64 to 65) is a custom exception that **inherits** from `ValueError`. Code that already catches `ValueError` still catches it, and code that wants to treat a bad annotation file specially can catch just this one.

## `load_traces` (lines 71 to 99)

```python
for lineno, line in enumerate(pathlib.Path(path).read_text().splitlines(), 1):
    if not line.strip():
        continue
    record = json.loads(line)
    missing = [f for f in TRACE_FIELDS if f not in record]
    if missing:
        raise ValueError(f"line {lineno}: missing fields {missing}")
```

The traces file is JSON Lines: one JSON object per line. `enumerate(..., 1)` hands back a counter alongside each line, starting at 1, so error messages can say which line is broken in terms a person would use. Blank lines are skipped, because an editor that adds a trailing newline shouldn't break the loader.

`[f for f in TRACE_FIELDS if f not in record]` is a **list comprehension** with a filter: "every required field that this record lacks". Collecting all the missing fields, instead of stopping at the first, gives a more useful error.

The `seen` **set** catches duplicate ids. A set answers "have I seen this?" instantly regardless of size. Duplicates matter here: if `t07` appeared twice, it would count twice in every rate.

The record is converted field by field into a `Trace`, with `tuple(record["retrieved"])` turning the JSON list into a tuple. An AI-written version often does `Trace(**record)` instead. That is shorter, but it crashes on any extra field in the file and leaves `retrieved` as a list. When you review a loader, check what it does with extra fields, missing fields, and duplicates.

## `load_taxonomy` (lines 102 to 114)

```python
severity = spec.get("severity")
if not isinstance(severity, int) or isinstance(severity, bool) or not 1 <= severity <= 3:
    raise ValueError(f"{mode}: severity must be an integer from 1 to 3")
```

The taxonomy is a dict of failure modes, each with a definition and a severity. `spec.get("severity")` uses **dict.get**, which returns `None` instead of raising an error when the key is missing; `None` then fails the integer check with a clear message.

The odd-looking `isinstance(severity, bool)` check exists because in Python `True` is an `int` (it equals 1). Without it, a taxonomy with `"severity": true` would load as severity 1. The tests include that exact case. `1 <= severity <= 3` is a **chained comparison**, read like the math: "between 1 and 3 inclusive".

Severity is a team judgment, and this function can't check whether it is a good one. It can only make sure every mode has one and that it is on the agreed scale.

## `write_annotation_template` (lines 117 to 127)

```python
with open(path, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["trace_id", "user_message", "bot_response", "outcome", "note", "failure_modes"])
```

`with open(...) as f:` is a **context manager**: the file is closed automatically when the block ends, even if something goes wrong halfway. `newline=""` is what the `csv` module's documentation asks for; without it you can get blank rows between records on some systems.

Why use `csv.writer` instead of joining strings with commas? Bot responses contain commas, quotes, and line breaks. The `csv` module quotes those cells correctly so the spreadsheet reads them back as one cell each. The test round-trips trace `t05` to prove it. A hand-rolled `",".join(...)` is a classic AI shortcut that works on clean test data and corrupts real data.

## `parse_modes` (lines 130 to 137)

```python
for part in (cell or "").split(";"):
    part = part.strip()
    if part and part not in modes:
        modes.append(part)
return tuple(modes)
```

People type `tone; invented_feature;;tone ` into spreadsheets. This function turns that into `("tone", "invented_feature")`: split on semicolons, trim spaces, drop empty pieces, drop repeats, keep the order they were typed. `(cell or "")` treats a missing cell (`None`) as empty text.

It keeps order with a list rather than using a set, because a set would scramble the order and the report lists modes as the annotator wrote them.

## `load_annotations` (lines 140 to 187)

```python
for n, row in enumerate(csv.DictReader(f), 1):
    outcome = (row.get("outcome") or "").strip().lower()
    if not outcome:
        continue
    ...
    row_problems: list[str] = []
    if trace_id not in known:
        row_problems.append("unknown trace_id")
    ...
    problems.extend(f"row {n} ({trace_id}): {p}" for p in row_problems)
...
if problems:
    raise AnnotationError("\n".join(problems))
```

This is the heart of the lab's checks and balances. `csv.DictReader` reads each row as a dict keyed by the header, so the code says `row["outcome"]` instead of `row[3]` and doesn't care about extra columns or column order.

Three design choices are worth noticing:

- **Blank outcome means "not annotated yet", not "error".** You can load a half-finished sheet and see partial results. The `.strip().lower()` means `" FAIL "` and `"Pass"` are accepted.
- **Every problem is collected, then reported at once.** The loop never stops at the first bad row. Each check appends to `row_problems`, and at the end one `AnnotationError` lists them all, one per line, as `row 4 (t04): fail needs a note or a failure mode`. If you've fixed a 36-row sheet one error at a time, you know why.
- **The taxonomy check is optional.** With `taxonomy=None` any label is accepted, which is what you want while you are still inventing labels (open coding). Once the taxonomy is fixed, pass it in and typos like `halucination` are caught.

`problems.extend(f"..." for p in row_problems)` passes a **generator expression** (a list comprehension in round brackets, computed lazily) to `extend`. The **f-string** (`f"row {n} ({trace_id}): {p}"`) inserts values into text.

Note the order of checks against the tests: `seen.add(trace_id)` runs after the duplicate check, so the second `t05` is the one flagged. Only rows with no problems become `Annotation` objects, but since any problem raises, a successful call returns every annotated row.

What to check in an AI-written version: does it stop at the first error; does it treat a blank outcome as a failure; does it count the header as row 1 (the spec says data rows start at 1); does it silently drop rows it can't parse instead of reporting them?

## Counting: `count_failure_modes`, `uncoded_failures`, `summarize` (lines 193 to 211)

```python
counts: Counter = Counter()
for a in annotations:
    if a.outcome == "fail":
        counts.update(set(a.failure_modes))
```

`Counter` (from `collections`) is a dict that counts. `counts.update(...)` adds one for each item you give it. Wrapping the modes in `set(...)` guarantees a trace counts at most once per mode, even if a mode somehow appears twice. Only failing traces count, so a stray label on a passing trace can't inflate a mode.

`uncoded_failures` (lines 202 to 204) lists failures that have a note but no label yet. Those are the traces you still owe axial coding, and the report calls them out instead of quietly leaving them out of the counts.

`summarize` (lines 207 to 211) uses a small trick: `sum(a.outcome == "pass" for a in annotations)` adds up `True` and `False` values, which count as 1 and 0. The `if n else 0.0` guard avoids dividing by zero on an empty sheet. On the reference data it returns 36 annotated, 13 passed, 23 failed, pass rate about 0.361.

## `prioritize` (lines 214 to 229)

```python
rate = count / n_annotated
out.append(Priority(mode, count, rate, severity, rate * severity))
return sorted(out, key=lambda p: (-round(p.score, 9), -p.count, p.mode))
```

This turns counts into a ranking. `rate` is the share of annotated traces showing the mode; `score` is rate times severity. Worked values on the reference data (36 traces):

| Mode | Count | Rate | Severity | Score |
|---|---|---|---|---|
| invented_feature | 9 | 0.250 | 3 | 0.750 |
| missed_handoff | 6 | 0.167 | 3 | 0.500 |
| answered_wrong_question | 5 | 0.139 | 2 | 0.278 |
| wrong_policy | 3 | 0.083 | 3 | 0.250 |
| tone | 4 | 0.111 | 1 | 0.111 |
| stale_pricing | 2 | 0.056 | 2 | 0.111 |

Notice that `wrong_policy` has fewer traces than `tone` but ranks above it. That is the point of severity weighting, and the README's "frequency and priority are different lists".

`sorted(..., key=lambda p: (...))` sorts by a **key function**. A **lambda** is a one-line unnamed function; this one returns a tuple, and Python compares tuples left to right, so ties on the first item fall through to the second. Negating the score and count makes them sort high to low while the mode name sorts A to Z.

The `round(p.score, 9)` is the subtle part. `tone` (4/36 times 1) and `stale_pricing` (2/36 times 2) are equal on paper, but floating-point arithmetic can make them differ in the last bit. Without rounding, which one ranks first would depend on that accident instead of on the count tie-breaker. An AI "simplifying" this to `key=lambda p: -p.score` would pass most tests and get this tie wrong.

## `render_report` (lines 232 to 273)

```python
lines = [
    "# Error analysis report",
    "",
    f"Annotated {s['annotated']} of {len(traces)} traces: {s['passed']} pass, {s['failed']} fail "
    f"(pass rate {s['pass_rate']:.1%}).",
    ...
]
for rank, p in enumerate(priorities, 1):
    lines.append(f"| {rank} | {p.mode} | {p.count} | {p.rate:.1%} | {p.severity} | {p.score:.2f} |")
```

The report is built as a list of lines and joined with newlines at the end. That is easier to read and change than one giant string. The format codes inside the f-strings do the presentation: `:.1%` turns 0.25 into `25.0%`, and `:.2f` shows two decimal places.

The function reuses `summarize`, `count_failure_modes`, and `prioritize` instead of recomputing anything, so the report can't disagree with the numbers the tests check.

For the top issues it prints the taxonomy definition and up to three example trace ids. The examples matter: a ranking without examples invites arguments about what a label means; three real traces settle it.

The "Caveats" section is not decoration. With 36 traces, one trace moves a rate by almost 3 points, and severity weights are opinions. A report that states its limits is easier to defend. If an AI rewrites this function, check that the caveats survive.

## Synthetic inputs: dimensions, prompt, and schema (lines 278 to 291)

```python
DIMENSIONS: dict[str, list[str]] = {
    "topic": ["refund", "integration", "feature how-to", "account security"],
    "plan": ["Starter", "Pro"],
    "style": ["terse", "frustrated", "multi-part question"],
}

class SyntheticQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(description="The customer's message, written in their own voice")
```

`DIMENSIONS` lists the axes you want test coverage on. `GEN_SYSTEM` is the system prompt for the generator: one message, in a customer's voice, no meta commentary.

`SyntheticQuery` is a **Pydantic model**: a class that describes the shape of data and validates it. Here it says the model's reply must be an object with exactly one text field, `query`. `extra="forbid"` rejects any extra fields. The `description` is sent along with the schema and acts as an instruction to the model.

## `make_tuples` and `tuple_to_prompt` (lines 294 to 311)

```python
names = list(dimensions)
for values in itertools.product(*(dimensions[n] for n in names)):
    t = dict(zip(names, values))
    if exclude is None or not exclude(t):
        out.append(t)
```

`itertools.product` gives every combination of the value lists (a **cross product**): 4 topics times 2 plans times 3 styles is 24 tuples. The `*` in `product(*...)` **unpacks** the sequence into separate arguments. `dict(zip(names, values))` pairs each dimension name with its value, giving `{"topic": "refund", "plan": "Starter", "style": "terse"}`.

`exclude` is an optional function (its type hint `Callable[[dict[str, str]], bool]` means "takes a dict, returns True or False"). Passing a function in, rather than hard-coding the rules, lets each product team drop combinations that make no sense for them.

`tuple_to_prompt` (lines 308 to 311) writes one `name: value` line per dimension inside `<profile>` tags. Tags keep the profile clearly separate from the instruction.

## `generate_queries` (lines 314 to 340)

```python
response = client.messages.parse(
    model=model,
    max_tokens=MAX_TOKENS,
    system=GEN_SYSTEM,
    messages=[{"role": "user", "content": tuple_to_prompt(t)}],
    output_format=SyntheticQuery,
)
if response.stop_reason in ("refusal", "max_tokens"):
    raise GenerationFailed(f"stop_reason={response.stop_reason} for {t}")
if response.parsed_output is None:
    raise GenerationFailed(f"no parsed output for {t}")
```

This is step two of two-step generation: one call per tuple, so each message is written for one profile. `client.messages.parse` with `output_format=SyntheticQuery` is the SDK's structured outputs helper, as the README describes; the validated object comes back as `response.parsed_output`.

`client` is a parameter, not created inside the function. That is **dependency injection**: the tests pass a fake client that records the calls and returns canned replies, so the logic is tested offline.

The checks run before the result is used. A refusal or a reply cut off at `max_tokens` raises `GenerationFailed` (a custom exception, lines 314 to 315) instead of producing a half-written test case. Failing loudly is the right choice for building a test set: a silently missing tuple is a coverage hole you'd never notice. The call also sends no `temperature` or other sampling parameters, which the README says the current API rejects; a test checks that.

## `main` (lines 346 to 358)

`main` wires the pipeline together on the reference data, writes `report.md` next to the code, and prints it. `if __name__ == "__main__":` means "only run this when the file is executed directly", so importing the module in tests doesn't write files.

## What the tests check

- **Loading** (`test_loads_all_traces_with_types`, `test_load_traces_skips_blank_lines_and_rejects_bad_records`, `test_taxonomy_loads_and_validates`, `test_annotation_template_round_trip`, `test_parse_modes`): file order is kept, blank lines skipped, duplicates and missing fields rejected, severity validated (including the `True` trap), and the CSV survives commas and quotes.
- **Validation** (`test_real_annotations_load`, `test_partial_annotation_is_allowed`, `test_every_problem_is_reported_at_once`, `test_taxonomy_check_is_optional`): partial sheets load, case is normalized, and a sheet with six different mistakes produces exactly six messages in row order.
- **Counting and ranking** (`test_counts_failing_traces_per_mode`, `test_counts_ignore_passes_and_repeat_codes`, `test_summarize`, `test_prioritize_*`): exact counts on the reference data, severity reordering, and both tie-breakers.
- **Report** (`test_report_structure`, `test_report_lists_uncoded_failures`): specific lines and section order.
- **Synthetic step** (`test_make_tuples_cross_product_and_filter`, `test_generate_queries_*`): cross product order, the filter, one call per tuple with the right arguments, no sampling parameters, and loud failure on refusal, truncation, or a missing parse.

What they don't check: whether the human labels are right (that is your job in step 2 of the README), whether the severity weights are sensible, whether a generated message actually matches its tuple, or that the live API behaves as the fake does. The single live test only checks that two real outputs are non-trivial and different.

## Review questions

1. An AI rewrites `load_annotations` to `raise AnnotationError(...)` inside the loop as soon as it finds a problem. Every existing check still exists. Which test fails, and why does it matter to the person using the tool?

<details>
<summary>Answer</summary>

`test_every_problem_is_reported_at_once` fails, because it expects all six problems in one message. For the annotator it means fixing a sheet one error per run instead of seeing every problem at once. The checks are the same; the usefulness is not.

</details>

2. Why does `count_failure_modes` wrap `a.failure_modes` in `set(...)` when `parse_modes` already removes duplicates?

<details>
<summary>Answer</summary>

Defense in depth. `Annotation` objects can be built directly (the tests do this with `("tone", "tone")`), bypassing `parse_modes`. The function's promise is "a trace counts at most once per mode", and it keeps that promise regardless of where its input came from.

</details>

3. `tone` has 4 failing traces and `wrong_policy` has 3. Why does `wrong_policy` rank higher, and what would you have to defend to your team about that?

<details>
<summary>Answer</summary>

Score is rate times severity: 3/36 times 3 is 0.25, while 4/36 times 1 is about 0.11. The ranking depends on the severity numbers in `taxonomy.json`, which are a judgment. You'd need to defend why a wrong refund policy is three times as bad as excessive apologizing (it can cost money and trust; tone mostly costs patience).

</details>

4. An AI removes the `round(..., 9)` from the sort key because "rounding a score before sorting loses precision". What could change?

<details>
<summary>Answer</summary>

`tone` and `stale_pricing` have equal scores on paper (4/36 times 1 and 2/36 times 2). As floats they can differ in the last bit, so the order between them would depend on rounding error instead of falling through to the count tie-breaker. `test_prioritize_weights_by_severity_and_breaks_ties` would be at risk.

</details>

5. Why does `load_annotations` skip rows with a blank outcome instead of raising an error?

<details>
<summary>Answer</summary>

So you can load a half-finished sheet. Blank means "not annotated yet", which is a normal state during annotation. A row with an outcome that is neither pass nor fail is different: that is a typo, and it is reported.

</details>
