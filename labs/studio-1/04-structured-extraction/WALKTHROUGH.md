# Walkthrough: Lab 04, structured extraction you can check

## What this code does

`solution.py` takes a messy business document (an email, a support ticket) and turns it into a list of action items that your code can trust. Each item has a task, an owner, a deadline, a priority, and a verbatim quote from the document that backs it up.

It gets there in four steps. First, the output shape is defined once, as Pydantic models. Second, Claude is called through the SDK's `client.messages.parse()` helper with **structured outputs**, so the reply is shaped by that schema. Third, if the reply fails a check that runs on your side, the code retries exactly once and tells the model what went wrong. Fourth, every evidence quote and every owner name is checked against the original document, and anything that isn't there gets flagged.

The point of the lab is the gap between step two and step four: **valid is not verified**. A reply can match the schema perfectly and still quote something the document never said. Only the last step catches that, and it is plain string matching, not another model call.

## How to read this lab

Open `work.py` beside this page. It starts as an exact copy of `solution.py`, so every line number here matches it until you change it. (If you don't have a `work.py` yet, run `python lab.py review all` from the `labs` folder.)

Run the tests from VS Code's **Testing** panel (the flask icon). Expand `studio-1 > 04-structured-extraction > test_extraction.py` and press the run button. The offline tests should all pass; the two `live` tests are skipped until you put an API key in `labs/.env`.

Read the sections below in order. Each one quotes the key lines, then explains what they do, why they're built that way, and what to look for when an AI writes a version of the same thing.

## Module docstring and imports (lines 1 to 18)

```python
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import anthropic
import pydantic
from pydantic import BaseModel, ConfigDict, Field, model_validator
```

The docstring at the top (lines 1 to 8) is the whole pipeline in five lines. That is worth copying as a habit: a reader, or a coding assistant asked to edit the file, sees the intended flow before reading any code.

`from __future__ import annotations` (line 9) tells Python to treat type hints as text instead of evaluating them right away. It lets the file use modern hint syntax like `str | None` everywhere and lets a class mention its own name in a hint (you'll see `-> "ActionItem"` later).

The imports are split into the standard library (`pathlib`, `dataclasses`, `datetime`, `typing`) and third-party packages (`anthropic`, `pydantic`). That split is a convention, not a rule, but it makes the review question "what does this need installed?" a one-glance check. Here the answer is two packages, both in `requirements.txt`.

## Settings and the system prompt (lines 20 to 32)

```python
MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
SAMPLES_DIR = pathlib.Path(__file__).parent / "samples"
```

Names in ALL_CAPS are **module constants**: values set once and read everywhere. Putting the model name in one place means switching to a cheaper model for a comparison is a one-line change, or an argument (as `extract` allows later).

`pathlib.Path(__file__).parent / "samples"` builds the path to the samples folder relative to this file, not relative to wherever you happened to run Python from. The `/` operator on a `Path` joins path pieces. AI-written scripts often use a bare `"samples"` string instead, which works only when you run from inside the lab folder.

The system prompt (lines 24 to 32) is a triple-quoted string. Read its rules as a list of the failure modes the code expects: invented tasks, paraphrased quotes, missing owners, and guessed dates. Notice that two of those rules ("evidence must be copied word for word", "If no specific person is responsible...") are also enforced in code further down. The prompt asks; the code checks. That pairing is the "checks and balances" theme of the course.

## `ActionItem`: the schema for one item (lines 38 to 68)

```python
class ActionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=3, description="What will be done, as a short imperative phrase")
    owner: str | None = Field(
        description="Name of the person responsible, as written in the document; null if no specific person is named"
    )
    ...
    priority: Literal["high", "medium", "low"] = Field(...)
    evidence: str = Field(min_length=10, description="A verbatim quote from the document, ...")
```

A class that inherits from `BaseModel` is a **Pydantic model**: you list fields with **type hints**, and Pydantic checks incoming data against them. `ActionItem.model_validate(some_dict)` either returns a typed object or raises `pydantic.ValidationError` listing every problem.

A few details carry a lot of weight here:

- `model_config = ConfigDict(extra="forbid")` (line 41) rejects any field that isn't declared. In the JSON Schema this becomes `"additionalProperties": false`. Without it, a model that invents an `assignee` field would pass silently and your code would never read it.
- `str | None` with no default (lines 44, 47, 50, 53) means **required but nullable**: the key must be present, and its value may be `null`. That is different from "optional". Forcing the key to appear makes the model decide, rather than quietly leave it out.
- `date | None` (line 50) means Pydantic turns the string `"2026-12-03"` into a real `datetime.date`. Your code then compares dates, not strings.
- `Literal["high", "medium", "low"]` (line 56) is a **Literal type**: only those exact strings are allowed. In the schema it becomes an enum, so `"urgent"` is rejected.
- `Field(..., description=...)` on every field matters because the descriptions travel with the schema to the model. They are part of the prompt. The tests check that none is missing.
- `min_length=3` and `min_length=10` (lines 43 and 60) block empty or trivial values. The README explains that the API's schema format supports only a subset of JSON Schema, so the SDK moves constraints like these into the description and checks them itself when the reply comes back. That client-side check is what can fail and trigger a retry.

```python
    @model_validator(mode="after")
    def _owner_or_reason(self) -> "ActionItem":
        if self.owner is None and not (self.owner_missing_reason or "").strip():
            raise ValueError("owner_missing_reason is required when owner is null")
        return self
```

`@model_validator(mode="after")` (lines 64 to 68) is a **decorator**: it registers the function below it as an extra check that runs after every field has passed its own validation. It is for rules that involve more than one field, which a type hint can't express. Raising `ValueError` inside it turns into a normal `ValidationError` for the caller.

`(self.owner_missing_reason or "").strip()` is a compact way to treat `None`, `""`, and `"   "` all as "no reason". `x or ""` gives `""` when `x` is `None`, and `.strip()` removes whitespace. A version that checks only `is None` would accept a reason of `"  "`.

When reviewing AI-written schemas, check: is `extra="forbid"` there; are nullable fields required (no `= None` default); does every field have a description; are cross-field rules in a validator rather than only in the prompt.

## `Extraction`: the wrapper (lines 71 to 76)

```python
class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ActionItem] = Field(description="Every action item in the document; an empty list if there are none")
```

The top level of the reply is an object with one key, `items`, holding a list of `ActionItem`. Wrapping the list in an object gives you a place to add document-level fields later (a summary, a detected language) without changing the shape of every item. The description says what to do when there are no items, which mirrors the last rule in the system prompt.

## `Flag` and `normalize` (lines 82 to 91)

```python
@dataclass
class Flag:
    index: int
    task: str
    problems: list[str]


def normalize(text: str) -> str:
    return " ".join(text.split())
```

`@dataclass` (line 82) is a decorator from the standard library that writes the boring parts of a class for you: the `__init__` that stores each field, a readable printout, and `==` comparison. Use a dataclass for plain records your own code creates; use Pydantic for data arriving from outside that needs validating. This file uses both, for exactly that reason.

`normalize` is one line with a lot packed in. `text.split()` with no argument splits on any run of whitespace (spaces, tabs, newlines) and drops empty pieces, so `"  a \n b\t\tc  "` becomes `["a", "b", "c"]`. `" ".join(...)` glues them back with single spaces: `"a b c"`.

Why only whitespace? Documents wrap lines in arbitrary places, and the model copies the words, not the line breaks. Normalizing whitespace makes a faithful quote match. Normalizing anything more (case, punctuation, stemming) would start letting paraphrases through, which is exactly what this check exists to catch. An AI asked to "make the matching more robust" will often add `.lower()` or fuzzy matching; treat that as a change in policy, not a cleanup.

## `verify_evidence`: the check that matters (lines 94 to 112)

```python
    text = normalize(source)
    flags: list[Flag] = []
    for i, item in enumerate(extraction.items):
        problems = []
        quote = normalize(item.evidence)
        if not quote or quote not in text:
            problems.append("evidence not found in source")
        if item.owner is not None and normalize(item.owner) not in text:
            problems.append("owner not found in source")
        if problems:
            flags.append(Flag(index=i, task=item.task, problems=problems))
    return flags
```

The source is normalized once, outside the loop (line 101), rather than once per item. `enumerate(...)` (line 103) gives each item along with its position, `0, 1, 2...`, so a flag can say *which* item is wrong.

`quote not in text` is Python's substring test: is this exact sequence of characters somewhere in the source? The `not quote or` part guards against an empty quote, because the empty string is "in" every string. The schema's `min_length=10` already blocks that, but the verifier doesn't assume the schema did its job. Each layer checks for itself.

The owner check works the same way. If the model writes `"Jordan Lee"` and that name appears nowhere in the email, it was invented. Note the limit: this only proves the name *appears*, not that the person is responsible. The README's "What to notice" section has a real example of a quote that passes and is still a judgment call.

Problems are collected in a list rather than returned on the first failure, so one flag can report both problems at once (the tests check the order: evidence first, then owner). Items with no problems produce no flag at all, so an empty return list means "everything checked out".

What to check in an AI-written verifier: that it matches exactly after whitespace normalization (no `.lower()`, no fuzzy ratio), that it guards empty quotes, and that it reports every problem with the item's index.

## Errors and the result record (lines 118 to 126)

```python
class ExtractionFailed(Exception):
    """Raised when no trustworthy extraction could be produced."""


@dataclass
class ExtractionResult:
    extraction: Extraction
    flags: list[Flag] = field(default_factory=list)
    attempts: int = 1
```

`ExtractionFailed` is a **custom exception**: a class that inherits from `Exception` and adds nothing but a name. The name is the point. A caller can write `except ExtractionFailed:` to handle "we couldn't get a trustworthy answer" without also catching unrelated bugs.

`field(default_factory=list)` gives each new `ExtractionResult` its own fresh empty list. Writing `flags: list[Flag] = []` instead is an error in a dataclass (Python refuses it), because a single list would otherwise be shared by every instance.

`attempts` records whether the retry was used. That number is cheap to log and useful later: if most documents need two attempts, the prompt or schema needs work.

## `build_messages` (lines 129 to 136)

```python
    return [
        {
            "role": "user",
            "content": f"<document>\n{document}\n</document>\n\nExtract the action items from this document.",
        }
    ]
```

One user message, built with an **f-string** (the `f"..."` prefix lets `{document}` drop the variable's value into the text). The document is wrapped in `<document>` tags so the model can tell the material apart from the instruction. The docstring notes there is no assistant prefill, because current models reject it; the tests check that the last message is from the user.

## `format_errors` and `retry_message` (lines 139 to 156)

```python
    for e in err.errors():
        where = ".".join(str(p) for p in e["loc"]) or "(root)"
        lines.append(f"{where}: {e['msg']}")
    return "\n".join(lines)
```

`err.errors()` returns a list of dictionaries, one per problem. Each has a `loc` (where the problem is, as a tuple such as `("items", 0, "evidence")`) and a `msg` (what's wrong). `".".join(str(p) for p in e["loc"])` turns that tuple into `items.0.evidence`. The `str(p)` matters because the `0` is an integer, and `join` only accepts strings. The `str(p) for p in ...` without square brackets is a **generator expression**: like a list comprehension, but it hands values to `join` one at a time instead of building a list first.

`or "(root)"` covers errors that belong to the whole object, such as the `model_validator` failing on a cross-field rule, where `loc` can be empty and the join gives `""`.

`retry_message` (lines 148 to 156) wraps that text in a user message. Feeding back the *specific* errors, as `field: message` lines, gives the model something concrete to fix. "Try again" with no detail mostly produces the same answer.

## `extract`: the call, the retry, and the stop reasons (lines 159 to 200)

The docstring (lines 160 to 170) states the policy in four bullets. Read it first; the code is a direct translation.

```python
    messages = build_messages(document)
    for attempt in (1, 2):
        try:
            response = client.messages.parse(
                model=model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=messages,
                output_format=Extraction,
            )
```

`for attempt in (1, 2):` (line 172) loops over a two-item tuple. It reads as "attempt one, then attempt two", and it makes the retry limit impossible to miss. A `while True` loop with a counter does the same thing with more places to get it wrong.

`client` is a parameter, not created inside the function. In real use it is `anthropic.Anthropic()`; in the tests it is a fake that records every call. Passing dependencies in like this is what makes the function testable without a network.

`client.messages.parse(..., output_format=Extraction)` (lines 174 to 180) passes the Pydantic **class itself**, not an instance and not a hand-written schema. Per the README, the SDK turns it into JSON Schema, sends it as `output_config.format`, and validates the reply against your original model, putting the result in `response.parsed_output`. Notice what is *not* in the call: no `temperature`, `top_p`, or `top_k`. The README says sampling parameters are rejected on the current API, and the tests fail if you send them.

```python
        except pydantic.ValidationError as err:
            if any(e["type"] == "json_invalid" for e in err.errors()):
                raise ExtractionFailed(
                    "reply was not valid JSON (likely truncated at max_tokens, or a refusal)"
                ) from err
            if attempt == 2:
                raise ExtractionFailed(f"output still invalid after a retry:\n{format_errors(err)}") from err
            messages = messages + [retry_message(err)]
            continue
```

`try` / `except pydantic.ValidationError as err` (lines 173 and 181) catches only validation failures. Network errors, authentication errors, and bugs still surface normally, which is what you want: retrying an authentication failure with "here are your validation errors" would be nonsense.

Inside, there are three outcomes, in this order:

1. **Broken JSON is not retried** (lines 182 to 185). `any(... for e in err.errors())` is true if at least one error has type `json_invalid`. Under constrained decoding, the README explains, broken JSON on a completed reply points to truncation or a refusal, and sending the same request again won't fix either. So it fails straight away.
2. **The second failure gives up** (lines 186 to 187), with the errors in the message so whoever reads the log can see why.
3. **Otherwise, retry with feedback** (lines 188 to 189). `messages + [retry_message(err)]` builds a *new* list with one extra message, and `continue` jumps to the next pass of the loop.

`raise ... from err` is **exception chaining**: the new `ExtractionFailed` keeps the original `ValidationError` attached, so a traceback shows both. Dropping `from err` loses the detail you need to debug.

```python
        if response.stop_reason == "refusal":
            raise ExtractionFailed("the model declined this request (stop_reason=refusal)")
        if response.stop_reason == "max_tokens":
            raise ExtractionFailed("output was truncated (stop_reason=max_tokens); raise max_tokens or split the input")
        extraction = response.parsed_output
        if extraction is None:
            raise ExtractionFailed("no parsed output in the response")
        return ExtractionResult(extraction=extraction, flags=verify_evidence(extraction, document), attempts=attempt)
```

If `parse` succeeded, the code still doesn't trust the result yet (lines 191 to 198). It checks `stop_reason` first: a refusal or a truncated reply is not an extraction, however it parsed. Then it checks that `parsed_output` is really there. Only then does it run `verify_evidence` against the original document and return.

Notice that a stop-reason failure is *not* retried. Like broken JSON, the same request would likely hit the same limit or the same refusal. The fix belongs to a person (raise `max_tokens`, split the document), and the error message says so.

The last line, `raise ExtractionFailed("unreachable")` (line 200), can't actually run: every pass through the loop either returns or raises. It is there so that if someone later edits the loop and breaks that guarantee, the function fails loudly instead of quietly returning `None`.

What to check when an AI writes this function: it retries at most once; it does not retry `json_invalid`; it feeds the errors back; it checks `stop_reason` before using `parsed_output`; it sends no sampling parameters; and it catches `ValidationError` specifically, not a bare `except Exception`.

## `main`: the demo script (lines 203 to 218)

```python
    for path in sorted(SAMPLES_DIR.glob("*.txt")):
        document = path.read_text()
        result = extract(client, document)
        ...
        flagged = {f.index: f.problems for f in result.flags}
        for i, item in enumerate(result.extraction.items):
            status = "FLAG " + ", ".join(flagged[i]) if i in flagged else "ok"
```

`main` runs the pipeline on every sample and prints a readable report. `sorted(SAMPLES_DIR.glob("*.txt"))` lists the sample files in a stable order. `{f.index: f.problems for f in result.flags}` is a **dict comprehension**: it builds a lookup from item index to its problems, so the print loop can ask "is item 2 flagged?" with `i in flagged`.

`A if condition else B` (line 211) is Python's **conditional expression**, a one-line if/else that produces a value. `item.owner or f"(none: {item.owner_missing_reason})"` uses `or` the same way as before: show the owner, or if there isn't one, show why.

`if __name__ == "__main__":` (lines 217 to 218) runs `main()` only when you execute the file directly (`python solution.py`). When the tests import the file, nothing runs and no API call happens.

## What the tests check

`test_extraction.py` has four groups.

- **Models** (seven tests): a valid item parses and `due_date` becomes a real `date`; unknown fields are rejected; priorities outside the three allowed values are rejected; `owner` must be present but may be null; a null owner needs a reason; empty `task` and `evidence` are rejected; and the generated JSON Schema is closed (`additionalProperties: false`), has exactly the seven expected fields, and describes every one.
- **Verification** (five tests): `normalize` collapses whitespace; a real quote that wraps across a line break passes; a paraphrase is flagged at the right index; an invented owner is flagged; and one flag can carry both problems, in order.
- **The call, with a fake client** (seven tests): the message ends with a user turn and contains the document; the happy path makes one `parse` call with the right class, the default model, enough `max_tokens`, and no sampling parameters; flags are computed on success; a validation error is retried once with the errors appended; a second failure raises `ExtractionFailed`; broken JSON is not retried; and `refusal` and `max_tokens` stop reasons fail without a retry.
- **Live** (two tests, skipped without a key): run both samples through the real API and check that at least one item is verified.

What they don't cover: whether the model found *all* the action items (recall), whether the owner it chose is the right person, whether priorities are sensible, or whether `due_phrase` is a real phrase from the document. The offline tests prove the plumbing and the verifier; judging the extraction's quality is a job for an eval set (Studio 3) or a human.

## Review questions

1. An AI "simplifies" `normalize` to `return text.strip().lower()`. Which existing test breaks, and what new risk does the change add?

<details>
<summary>Answer</summary>

`test_normalize_collapses_whitespace` breaks, because `strip()` only trims the ends and leaves the internal newline and tabs. `test_verbatim_quote_across_a_line_break_passes` would also fail, since the email wraps the sentence after "once the" and the quote has a space there. The new risk is `.lower()`: a quote that differs from the source in capitalization would now pass, which loosens "word for word" without anyone deciding to.

</details>

2. Why does `extract` refuse to retry when the error type is `json_invalid`, but retry other validation errors?

<details>
<summary>Answer</summary>

Under constrained decoding, broken JSON on a completed reply points to truncation at `max_tokens` or a refusal (the README's explanation). Sending the same request again would hit the same problem and cost another call. Other validation errors come from client-side checks the API schema can't express (like `min_length` or the owner-or-reason rule), and the model can usually fix those once it's told exactly what failed.

</details>

3. The schema declares `owner: str | None = Field(description=...)` with no default. What would change if an AI added `= None` as a default?

<details>
<summary>Answer</summary>

`owner` would become optional: the key could be left out entirely, and the generated schema would no longer list it as required. `test_owner_is_required_but_nullable` would fail. The design choice is to make the model state "null" on purpose (and give a reason), rather than let it silently skip the field.

</details>

4. `verify_evidence` passes an item whose evidence is "someone on your side should double-check the delivery address for the Denver warehouse." Does that mean the item is correct?

<details>
<summary>Answer</summary>

No. It means the quote is real. The verifier can't tell whether the sentence is a genuine action item, who should own it, or whether the model's `owner_missing_reason` is sensible. That is a judgment call for a second check (a different model, or a person), which lesson 9 covers. A passing verifier narrows what a human has to look at; it doesn't replace them.

</details>

5. `ExtractionResult` uses `field(default_factory=list)` for `flags`. Why not just `flags: list[Flag] = []`?

<details>
<summary>Answer</summary>

Dataclasses refuse a plain mutable default like `[]` (Python raises an error when the class is defined), because one list would be shared by every result object. `default_factory=list` calls `list()` fresh for each new instance, so each result has its own list.

</details>
