# Walkthrough: a prompt test harness

## What this code does

`solution.py` turns "this prompt seems better" into a measurement. It holds two versions of a
support-ticket triage prompt, runs each one over the same ten test tickets in `cases.json`, applies
small programmatic checks to every output (does it parse as JSON, is the category right, is it short
enough), and prints a table of PASS and FAIL per case with a pass rate per version.

The file is organized as a pipeline, top to bottom: the prompt versions, then loading and rendering
(turning a test case into the exact text sent to the model), then the checks, then calling the model
and running the suite, then the report. Each stage is a small function you can test on its own, which
is why almost every test in this lab runs offline with a fake client.

The design idea worth taking away: **checks are code, so they are cheap and repeatable.** Once the
harness exists, you can rerun every case after every prompt change in seconds and see exactly which
cases got fixed and which regressed, instead of eyeballing two or three outputs.

## How to read this lab

Open `work.py` beside this page. It starts as a copy of `solution.py`, so the line numbers below
match it until you change something. Read a section here, then the code it points to.

Run the tests from VS Code's **Testing** panel (the flask icon): expand
`studio-1/03-prompt-test-harness` and press the run button. Everything except the one `live` test
runs without an API key. If you want to see a test fail on purpose, change something small in
`work.py` (swap the order of two `.replace` calls, say), rerun, read the message, and undo it.

## Imports and constants (lines 7 to 17)

```python
from __future__ import annotations

import argparse
import json
import pathlib
import re
from string import Template

HERE = pathlib.Path(__file__).parent
DEFAULT_MODEL = "claude-opus-5-5"
CATEGORIES = ["billing", "bug", "account", "feature_request", "other"]
```

Everything imported here ships with Python; the `anthropic` SDK is imported later, inside `main`
(more on that below).

- `from __future__ import annotations` (line 7) makes Python treat **type hints** (the `: str` and
  `-> list[dict]` annotations on functions) as plain text instead of evaluating them. It lets newer
  hint syntax like `str | pathlib.Path` work on older Python versions. Hints don't change what the
  code does; they document what each function expects and returns.
- `argparse` reads command-line options, `json` parses JSON, `pathlib` handles file paths, `re` is
  regular expressions, and `Template` is a simple text-substitution class (explained under the
  prompts).
- `HERE` (line 15) is the folder this file lives in. `__file__` is the path of the current file, and
  `.parent` is its folder. Building paths from `HERE` means `cases.json` is found no matter which
  folder you run the script from.
- `DEFAULT_MODEL` and `CATEGORIES` are **constants** (capital names, by convention, set once).
  Putting the model name in one place means one edit changes it everywhere.

**When reviewing:** a new import is a quick signal that the code's job has grown. An AI-written
harness that imports, say, `requests` or a templating library has taken on a dependency you'd have
to install and trust.

## The prompt versions (lines 19 to 53)

```python
PROMPTS: dict[str, dict[str, str]] = {
    "v1": {
        "system": "",
        "user": Template("Classify this support ticket and tell me how urgent it is.\n\n$ticket"),
    },
    "v2": {
        "system": ("You triage support tickets for Ledgerly, ..."),
        "user": Template("<ticket>\n$ticket\n</ticket>\n\n" "<categories>\n" ...),
    },
}
```

`PROMPTS` is a **nested dict**: version name to a dict with a `"system"` prompt and a `"user"`
template. The comment above it (lines 19 to 22) states the rule that makes the comparison honest: a
published version is immutable. To change a prompt you add `"v3"` and compare, so old results stay
reproducible.

A few constructs to notice:

- **Adjacent string literals** (lines 29 to 33 and 34 to 51). Python joins strings written next to
  each other inside parentheses into one string. `("abc " "def")` is `"abc def"`. It's how you write
  a long prompt across many lines without one enormous line. Watch the spaces at the ends of the
  pieces: forget one and two words run together in the prompt.
- **`string.Template`**. The placeholder is `$ticket`, and `.substitute(ticket=...)` fills it in.
  Why not an f-string or `str.format`? Because v2 contains literal JSON braces (line 49,
  `{"category": ...}`). `str.format` treats every `{...}` as a placeholder and would crash on them;
  `Template` only looks at `$`, so braces are safe. The flip side: a literal `$` in the template text
  (for example "charges over $100") would now be misread as a placeholder and raise an error, so it
  would have to be written `$$`.
- **What v2 does differently.** It gives a role and the reason labels matter (system prompt), puts
  the ticket first inside `<ticket>` tags, defines each category, says to treat ticket text as data,
  gives an explicit urgency rule and a tie-break rule ("the one that hurts the customer most"), and
  ends with the exact output format. These are week 2's fundamentals, each one a line you can point
  at.

**When reviewing:** compare versions line by line. If an AI "improves" v2 by editing it in place, the
old results no longer describe any prompt that exists. Also check that every category the checks
expect (`cases.json`) is defined in the prompt.

## `load_cases` (lines 59 to 77)

```python
data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
cases = data.get("cases") if isinstance(data, dict) else None
if not isinstance(cases, list) or not cases:
    raise ValueError("file must contain a non-empty 'cases' list")
seen: set[str] = set()
for i, case in enumerate(cases):
    cid = case.get("id")
    if not cid or not isinstance(case.get("input"), str) or not case.get("checks"):
        raise ValueError(f"case {cid or i} needs an id, an input string, and checks")
    if cid in seen:
        raise ValueError(f"duplicate case id {cid}")
    seen.add(cid)
return cases
```

This reads the test set and refuses to run on a broken one. Line 65 reads the file as text (with an
explicit `utf-8` encoding, so the Spanish ticket's accents load the same on every computer) and
parses the JSON.

- Line 66 uses a **conditional expression** (`A if condition else B`) with `isinstance`, which
  checks a value's type. If the file's top level isn't a dict, there's no `"cases"` key to look up,
  so it falls back to `None` instead of crashing.
- `dict.get("cases")` returns `None` when the key is missing, where `data["cases"]` would raise
  `KeyError`. That lets line 67 produce one clear error message for every kind of bad file.
- `enumerate(cases)` (line 70) gives the position and the item together, so the error message can
  name a case by its id or, if it has none, by its position (`cid or i`: `or` returns the first
  truthy value).
- The `seen` **set** catches duplicate ids. Duplicates matter because results are compared by case
  id; two cases with the same id would make the comparison silently wrong.

**Why validate at all?** A harness that quietly skips a case with no checks reports a higher pass rate
than it should, because a case with nothing to check can't fail. Failing loudly at load time is a
**checks and balances** move on the test set itself.

**When reviewing:** look for validation that was "simplified" away. An AI version that just returns
`json.load(f)["cases"]` passes the happy-path test and loses every guard.

## `escape_for_xml` (lines 80 to 82)

```python
return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
```

This is the same function as the lesson 4 exercise. Each `.replace` returns a new string (strings
never change in place), and chaining them applies the three replacements in order. The `&` must go
first; otherwise the `&` inside a freshly written `&lt;` would be escaped again into `&amp;lt;`.

It exists for the `tag-breakout` case, whose ticket contains `</ticket>`. Escaped, that text can't
close the ticket block early. As the README says, escaping protects the prompt's **structure**; it
does not stop a model from obeying instructions written inside the ticket.

## `render_prompt` (lines 85 to 92)

```python
spec = PROMPTS[version]
return {"system": spec["system"], "user": spec["user"].substitute(ticket=escape_for_xml(ticket))}
```

Two lines that turn a version name and a ticket into the exact request content. `PROMPTS[version]`
uses square brackets on purpose: an unknown version like `"v99"` raises `KeyError` immediately,
which the docstring promises and a test checks. Using `.get` here would return `None` and fail later
with a confusing error.

The ticket is escaped **here, at the one place where untrusted text enters the prompt**. Doing it in a
single place means no prompt version can forget it. Note that v1 is escaped too, even though v1 has
no tags; escaping is harmless there and keeps the rule simple.

**When reviewing:** check that untrusted text passes through exactly one escape. Escaping twice (once
here and once in a caller) produces `&amp;lt;` in the prompt; escaping zero times reopens the
breakout.

## `parse_json_output` and the fence pattern (lines 98 to 113)

```python
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

def parse_json_output(text: str):
    s = text.strip()
    m = _FENCE.match(s)
    if m:
        s = m.group(1)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None
```

Models often wrap JSON in a Markdown code fence (three backticks, sometimes followed by `json`).
This helper accepts one such fence and otherwise insists on clean JSON.

- `re.compile` (line 98) builds the **regular expression** once, at import time, instead of on every
  call. The leading underscore in `_FENCE` is a convention for "internal to this module."
- Reading the pattern: `^` start, three backticks, `(?:json)?` an optional `json` (the `?:` makes a
  group that isn't captured), `\s*` any whitespace, `(.*?)` the content (captured, and **lazy**, so it
  takes as little as possible), `\s*`, three backticks, `$` end. `re.DOTALL` lets `.` match newlines,
  which multi-line JSON needs. The `r"..."` prefix is a **raw string**, so backslashes reach the regex
  engine untouched.
- `m.group(1)` (line 109) is the captured content inside the fence.
- **`try` / `except`** (lines 110 to 113): attempt the parse, and if `json.loads` raises
  `JSONDecodeError`, return `None` instead of crashing. A check should report "failed", not stop the
  whole suite because one output was malformed.

**Why so strict?** Because the anchors mean "Sure! Here's the JSON: {...}" does **not** parse. That is
deliberate: if your production code would choke on chatty output, the test should too. A more
forgiving parser (searching for the first `{` anywhere) would make the pass rate look better than
what your real pipeline would see.

**When reviewing:** watch for an AI catching every exception with a bare `except:` (it hides real bugs,
like a typo in a variable name) or quietly loosening the parser so more outputs "pass."

## `run_check` (lines 116 to 141)

```python
kind = check.get("type")
if kind == "contains":
    return check["value"] in output
...
if kind in ("json_parses", "json_field_equals", "json_field_in"):
    obj = parse_json_output(output)
    if kind == "json_parses":
        return obj is not None
    if not isinstance(obj, dict):
        return False
    value = obj.get(check["field"])
    if kind == "json_field_equals":
        return value == check["value"]
    return value in check["values"]
raise ValueError(f"unknown check type: {kind!r}")
```

Each check in `cases.json` is a small dict like `{"type": "json_field_equals", "field": "category",
"value": "billing"}`. `run_check` is a **dispatcher**: it looks at `type` and runs the matching
comparison, returning `True` or `False`.

- The string checks (lines 123 to 130) are one-liners. `in` tests for a substring, and it is
  **case-sensitive**: `"refund"` is not in `"please REFUND me"`, which a test pins down. `re.search`
  finds the pattern anywhere and returns `None` when there's no match.
- The JSON checks share one parse (line 132), grouped by `kind in (...)`, a **tuple** of names.
- `isinstance(obj, dict)` (line 135) handles output that is valid JSON but not an object, such as
  `[1, 2]`. Without it, `obj.get` would crash on a list.
- `obj.get(check["field"])` returns `None` for a missing field, so a missing category simply fails
  the comparison. Notice the mix: `.get` on the model's output (which may be missing things) but
  square brackets on the check (which you wrote, and which should be complete).
- `json_field_equals` is exact: `"Bug"` does not equal `"bug"`. That's right for labels that code
  will route on.
- The last line raises for an unknown type. `{kind!r}` in the **f-string** inserts the value's
  `repr`, so you see `'vibes'` with quotes (and `None` if the type is missing).

**Why raise instead of returning False?** A typo in `cases.json` (`"json_feild_equals"`) would
otherwise make a check fail forever, and you'd blame the prompt. Raising makes a broken test look
broken.

**When reviewing:** check that each new branch returns a real `bool`, that the JSON branches share
`parse_json_output` (so fenced output is treated consistently), and that the final `raise` is still
the fall-through. CHANGE.md asks you to add a check type here.

## `call_model` (lines 147 to 163)

```python
kwargs = {
    "model": model,
    "max_tokens": 2048,
    "output_config": {"effort": "low"},
    "messages": [{"role": "user", "content": rendered["user"]}],
}
if rendered.get("system"):
    kwargs["system"] = rendered["system"]
response = client.messages.create(**kwargs)
return "".join(block.text for block in response.content if block.type == "text")
```

This sends one request and returns the reply text.

- The request is built as a dict, `kwargs`, and passed with `**kwargs` (line 162). The double star
  **unpacks** the dict into keyword arguments, so `create(**{"model": m})` is the same as
  `create(model=m)`. Building a dict first is what makes line 160 possible: the `system` key is added
  only when there is a system prompt. v1 has none, and a test checks that the request then has no
  `system` key at all.
- There are no sampling parameters such as `temperature`. The docstring records why (the current API
  rejects them), and a test checks they're absent.
- The last message is the user turn: no prefilled assistant reply, which current models reject.
- `output_config` sets low effort, keeping a 20-call comparison cheap.
- The reply's `content` is a list of **blocks**. Current models can return a thinking block before
  the text, so line 163 keeps only blocks whose `type` is `"text"`, using a generator expression inside
  `"".join(...)`. The docstring's warning, "never by position", is the point: code that takes
  `response.content[0].text` works until a thinking block shows up first, then crashes. The fake
  client in the tests returns a thinking block first precisely to catch that.

**Why take `client` as an argument?** So tests can pass a fake one that records requests and returns
canned text. This is the same "accept your dependencies as inputs" pattern from the temperature
walkthrough, and it's why this whole lab can be checked without a key.

## `run_suite` (lines 166 to 179)

```python
for case in cases:
    output = call_model(client, render_prompt(version, case["input"]), model)
    failed = [c for c in case["checks"] if not run_check(c, output)]
    results.append(
        {"id": case["id"], "version": version, "output": output, "passed": not failed, "failed": failed}
    )
```

For each case: render, call, then run every check. The **list comprehension** on line 175 keeps the
checks that failed, so the report can say which check broke, not just that the case did.

`"passed": not failed` uses **truthiness**: an empty list is false, so `not []` is `True` (all checks
passed), and any failed check makes it `False`. A case passes only if **every** check passes.

The output is stored with the result. That's what lets `main` print failing outputs for you to read,
which is step 4 of the README and the most useful part of the exercise.

**When reviewing:** confirm results come back in the same order as `cases` (a test checks this, and
`format_table` relies on it), and that one bad output can't stop the loop (it can't, because
`parse_json_output` never raises).

## `pass_rate` (lines 182 to 184)

```python
return sum(r["passed"] for r in results) / len(results) if results else 0.0
```

`True` counts as 1 when summed, so the sum is the number of passing cases. The conditional expression
guards against dividing by zero on an empty list. Returning `0.0` there is a choice (a test pins it),
and arguably raising would be safer; a 0% that means "no data" can be mistaken for "everything
failed."

## `format_table` (lines 187 to 200)

```python
versions = list(results_by_version)
ids = [r["id"] for r in results_by_version[versions[0]]]
width = max(len("pass rate"), *(len(i) for i in ids))
lines = ["case".ljust(width) + "".join(v.rjust(8) for v in versions)]
for i, cid in enumerate(ids):
    cells = ["PASS" if results_by_version[v][i]["passed"] else "FAIL" for v in versions]
    lines.append(cid.ljust(width) + "".join(c.rjust(8) for c in cells))
```

This builds the plain-text report: a header row, one row per case, and a pass-rate row.

- `list(results_by_version)` gives the dict's keys (the version names), in insertion order.
- Line 193 uses `*` to **unpack** a generator into separate arguments to `max`, so the first column
  is as wide as the longest case id or the words "pass rate", whichever is longer.
- `ljust(width)` pads a string with spaces on the right to a given width; `rjust(8)` pads on the left
  to right-align each version's column.
- Line 198 rounds each rate to a whole percent inside an f-string.

**A hidden assumption:** line 196 looks up row `i` in every version's results, so it assumes every
version ran the same cases in the same order. `run_suite` guarantees that when all versions get the
same `cases` list, as `main` does. If someone later runs versions on different case files, this table
would quietly line up the wrong rows. A reviewer should notice when code relies on positions lining
up rather than on ids.

## `main` (lines 203 to 224)

```python
import anthropic
...
client = anthropic.Anthropic()
cases = load_cases(args.cases)
results = {v: run_suite(client, cases, v, args.model) for v in args.versions}
print(format_table(results))
```

The command-line entry point. `import anthropic` sits inside the function so that importing this file
(which every test does) never needs the SDK or a key; only running it as a script does.

- `argparse` defines the options. `nargs="+"` on `--versions` means "one or more values," so
  `--versions v1 v2` becomes the list `["v1", "v2"]`.
- `anthropic.Anthropic()` creates the real client, reading the key from the environment.
- Line 214 is a **dict comprehension**: version name to that version's results.
- Lines 216 to 220 print each failure with the check types that failed and the first 200 characters
  of the output. `[:200]` is a **slice**, and `!r` shows the text with quotes and visible escape
  characters, so you can tell an empty reply from a whitespace one.
- `if __name__ == "__main__":` (line 223) runs `main()` only when the file is executed directly, not
  when it's imported by the tests.

## What the tests check

All in `test_prompt_harness.py`. Everything except the last test runs offline.

- **Loading** (`test_load_cases_*`): the real `cases.json` loads with ten complete cases, and a file
  with a case missing its checks, or with duplicate ids, raises `ValueError`.
- **Rendering** (`test_escape_for_xml`, `test_render_*`): escaping works; a ticket containing
  `</ticket>` leaves exactly one closing tag; v2 puts the ticket before the instructions and has a
  system prompt; an unknown version raises `KeyError`.
- **Checks** (`test_run_check`, parametrized over 16 cases): each check type passes and fails where it
  should, including case sensitivity, fenced JSON, chatty non-JSON, valid JSON that isn't an object,
  and exact label matching. An unknown type raises.
- **Request shape** (`test_call_model_*`, with a `FakeClient`): the model and system prompt are passed
  through, the last message is from the user, effort is low, `temperature`/`top_p`/`top_k` are absent,
  the thinking block is skipped, and an empty system prompt is left out entirely.
- **The suite** (`test_run_suite_and_pass_rates`): with a fake model that answers v1 in prose and v2
  in JSON, it makes 20 calls, keeps case order, gives v1 a 0% pass rate, and v2 exactly 50% (the fake
  always answers "bug, low" except for the double-charge ticket, so 5 of 10 cases pass). It also checks
  that a failing case records which check failed.
- **Reporting** (`test_pass_rate_empty`, `test_format_table`): the empty-list rate and the table's
  rows and percentages.
- **Live** (`test_live_v2_on_two_cases`, skipped without a key): two real calls on a small model, and
  only one assertion, that the output parses as JSON.

What they **don't** check: whether a real model's labels are correct (the live test only checks
format), whether summaries are faithful to the ticket (that needs a human or a model grader, Studio
3), whether results are stable across repeated runs, and the `main` function's printing. The checks
themselves can be wrong too: a test case with a mistaken expected label will fail a correct model
forever, which is why step 4 asks you to decide, for every failure, whether the prompt, the check, or
the case is at fault.

## Review questions

1. Why does `render_prompt` escape the ticket, rather than each prompt template doing it?

   <details><summary>Answer</summary>

   Because it is the single place untrusted text enters a prompt. Escaping there guarantees every
   version, including ones added later, gets it exactly once. If templates did it, a new version
   could forget, and the `tag-breakout` ticket would close the tag again.

   </details>

2. An AI rewrites `call_model`'s last line as `return response.content[0].text`. The offline tests
   fail. Why, and why does that failure matter for production?

   <details><summary>Answer</summary>

   The fake client returns a thinking block first, and a thinking block has no `text` attribute, so
   the line raises `AttributeError`. Current models can return thinking blocks before text, so the
   same code would crash in production. Select blocks by `type`, never by position.

   </details>

3. `parse_json_output` rejects `Sure! Here is the JSON: {"category": "bug"}`. Should you loosen it
   so that output passes?

   <details><summary>Answer</summary>

   Usually not. The harness should judge outputs the way your real pipeline would read them. If
   production code needs clean JSON, a chatty reply is a real failure, and the fix belongs in the
   prompt (or in structured outputs, week 3), not in a more forgiving test. Loosening the parser
   makes the pass rate look better without making the product better.

   </details>

4. v2 passes 8 of 10 cases and your new v3 passes 9 of 10. Is v3 better?

   <details><summary>Answer</summary>

   Not yet proven. Check per case: if v3 fixed two cases and broke one, the regression needs
   investigating before you ship. And since output varies between runs, rerun both versions (more
   than once) before trusting a one-case difference. The table makes the comparison visible; it
   doesn't make a small difference significant.

   </details>

5. Why does `run_check` raise `ValueError` for an unknown check type instead of returning `False`?

   <details><summary>Answer</summary>

   A misspelled type in `cases.json` would otherwise fail on every run, and you'd spend time
   "fixing" a prompt that was never the problem. Raising makes a broken test visibly broken, which is
   checks and balances applied to the test set itself.

   </details>
