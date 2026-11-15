# Walkthrough: workflow patterns for a status update

## What this code does

`solution.py` turns raw meeting notes into a status update for one of three audiences (executives, the project team, or the client). It strings together three patterns from Anthropic's "Building effective agents": **routing** (a cheap model picks the audience), **prompt chaining with a gate** (one call extracts facts, plain code checks them, a second call drafts from the checked facts only), and **evaluator-optimizer** (code checks and then a reviewer model critique the draft, and the drafter revises).

Every step is chosen by your code, never by the model. That is what makes this a workflow and not an agent: the model fills in text at fixed points, and Python decides what happens next. The payoff is that each decision point is a small function you can test without an API key.

The other theme is **checks and balances**. Structured outputs guarantee the JSON shape, but only the gate knows whether a quote really appears in the notes. Code checks catch the mechanical failures (too long, a missing owner, a leaked codename) before you pay a second model to judge the draft. And when the loop runs out of rounds, the result is flagged `approved=False` for a person instead of being shipped.

## How to read this lab

Open `work.py` beside this page. It starts as a copy of `solution.py`, so the line numbers below match it until you change it. Read a section here, then the matching lines there.

Run the tests from VS Code's **Testing** panel (the flask icon): expand `test_workflow_patterns.py` and run it. Every offline test should pass. The tests use a `FakeClient` that returns scripted replies, so you can read a test, see exactly which "model" replies it scripts, and trace how the code reacts.

## Configuration: models, limits, and audiences (lines 17 to 41)

```python
MODEL = "claude-opus-5-5"  # drafting
ROUTER_MODEL = "claude-haiku-5-5"  # cheap, fast classification
EVALUATOR_MODEL = "claude-sonnet-5-5"  # a different model from the drafter, for the rubric review
...
FALLBACK_AUDIENCE = "team"  # internal, so a misroute never sends internal detail outside

AUDIENCES = {
    "exec": {"max_words": 120, "include_risks": True, "instructions": "..."},
    ...
}
```

These are **module-level constants**: names in capital letters, set once at the top, read everywhere else. Putting them here means a reviewer can see every model choice and every limit in one screen, and a test can refer to `lab.ROUTER_MODEL` instead of repeating the string.

Three model choices, three jobs. Classification is easy, so it goes to the cheapest model. Drafting is the hard writing, so it gets the strongest. The reviewer is deliberately a **different** model from the drafter, so it does not share every blind spot of the model whose work it judges. This is model selection as a design decision, not a default.

`AUDIENCES` is a **dict of dicts**: each audience name maps to its own settings. Adding a fourth audience means adding one entry, and every function that reads `AUDIENCES[audience]["max_words"]` picks it up. Look at `include_risks`: the client entry sets it to `False`, which is how risks are kept out of client drafts (see `facts_for`).

`FALLBACK_AUDIENCE = "team"` is the most important safety choice in the file. When the router is confused, the update goes to an **internal** audience. A confused router that defaulted to `client` could send a confidential margin note outside the company. When you review AI-written routing code, always ask: what happens on the unhappy path, and is that the safe direction?

## System prompts (lines 43 to 57)

```python
ROUTER_SYSTEM = """You classify requests for project status updates by audience.
Reply with exactly one word: exec, team, or client.
..."""
```

Triple-quoted strings (`"""..."""`) can span several lines, which makes prompts readable in code. Each prompt is short and states the one job of its step. Notice that the extraction prompt (lines 47 to 51) asks for a word-for-word `quote` and says `owner` may be null. Those two rules are what the gate later enforces in code. A prompt rule without a code check is a hope; a prompt rule with a code check is a contract.

## Output schemas (lines 59 to 92)

```python
FACTS_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["items"],
        ...
                        "kind": {"type": "string", "enum": ["decision", "action", "risk", "update"]},
                        "owner": {"anyOf": [{"type": "string"}, {"type": "null"}]},
```

These are **JSON Schemas** passed to the API as structured outputs, so the model's reply is guaranteed to be valid JSON of this shape. `enum` limits `kind` to four values. `anyOf` with a `null` branch lets `owner` be missing on purpose, which is how the model says "nobody was named". `additionalProperties: False` forbids extra keys.

What a schema cannot do is check truth. A perfectly shaped item can carry a quote that never appeared in the notes. That is why the gate exists. `VERDICT_SCHEMA` (lines 84 to 92) gives the reviewer a fixed shape too: a boolean `pass` and a list of `problems`.

## Two exception types (lines 95 to 100)

```python
class StepFailed(Exception):
    """A model call ended without a usable answer (refusal, truncation, no text)."""


class GateFailed(Exception):
    """The chain's gate rejected the extraction, so nothing was drafted."""
```

A **custom exception** is a class that inherits from `Exception`; the docstring is the whole body. Having two named types lets the caller tell "the model call broke" apart from "the model answered, but nothing it said was supported by the notes". Those need different responses: retry or alert in the first case, show a person the rejected items in the second.

## `text_of` (lines 106 to 118)

```python
    if response.stop_reason in ("refusal", "max_tokens"):
        raise StepFailed(f"model stopped early: stop_reason={response.stop_reason}")
    for block in response.content:
        if block.type == "text":
            return block.text
    raise StepFailed("response contained no text block")
```

A response's `content` is a list of blocks, and current models may put thinking blocks before the text. So the loop takes the **first block whose type is `"text"`**, not simply `content[0]`. An AI-written version that does `response.content[0].text` works until the model thinks first, then crashes.

The `stop_reason` check comes first. `"max_tokens"` means the reply was cut off (half a JSON object is worse than none), and `"refusal"` means the model declined. Both raise `StepFailed` with an **f-string** message (`f"...{value}..."` fills in the value) that says why. Failing loudly here is the right call: every later step assumes it has a complete answer.

## `call` (lines 121 to 138)

```python
def call(client, *, model: str, system: str, prompt: str, effort: str = "medium", schema: dict | None = None) -> str:
    output_config: dict = {"effort": effort}
    if schema is not None:
        output_config["format"] = schema
    response = client.messages.create(
        model=model, max_tokens=MAX_TOKENS, system=system,
        output_config=output_config,
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(response)
```

This is the only function that touches the API, and every other function goes through it. That makes it the one place to check the request shape.

- The bare `*` in the parameter list means everything after it is **keyword-only**: you must write `model=...`, `prompt=...`. That prevents a quiet mix-up of `system` and `prompt`, which are both strings.
- The **type hints** (`model: str`, `schema: dict | None = None`, `-> str`) document what each parameter is. `dict | None` means "a dict or nothing". The `from __future__ import annotations` on line 10 lets this newer hint syntax work on older Python versions too.
- `client` is passed in rather than created inside. That is **dependency injection**: the tests hand in a `FakeClient`, and production hands in `anthropic.Anthropic()`. Without this, the code could not be tested offline.
- The docstring records what is deliberately absent: no assistant prefill and no `temperature`, `top_p`, or `top_k`. The tests check that those keys are never sent. An AI assistant trained on older examples will often add `temperature=0`; this is the kind of "helpful" addition to catch in review.

## Routing: `Route` and `parse_audience` (lines 144 to 154)

```python
@dataclass
class Route:
    audience: str
    raw: str
    fell_back: bool


def parse_audience(raw: str) -> str | None:
    label = raw.strip().rstrip(".").strip().lower()
    return label if label in AUDIENCES else None
```

`@dataclass` is a **decorator** that writes the boilerplate for a simple record class: it generates `__init__`, a readable printout, and equality from the annotated fields. `Route` keeps three things: the audience used, the router's raw text (so you can see what it actually said), and whether it fell back (so you can count how often the router is confused).

`parse_audience` is a **strict parser**. It allows exactly three kinds of cleanup (whitespace, trailing periods, case), then demands an exact match. `" Exec.\n"` becomes `"exec"` and is accepted. `"client or exec?"` and `"executive"` are rejected. The one-line `x if condition else y` is a **conditional expression**.

Why strict? A looser version that searches for a label anywhere in the text (`if "client" in raw`) would route the hedge "Probably client, but it could be exec" to the client. A hedge is not a decision. When reviewing AI-written parsers, look for `in` checks on free text: they turn uncertainty into a confident wrong answer.

## `route_audience` (lines 157 to 167)

```python
    raw = call(client, model=ROUTER_MODEL, system=ROUTER_SYSTEM, prompt=request, effort="low")
    audience = parse_audience(raw)
    if audience is None:
        return Route(audience=FALLBACK_AUDIENCE, raw=raw, fell_back=True)
    return Route(audience=audience, raw=raw, fell_back=False)
```

The cheap model at low effort does the classification, the strict parser judges it, and `None` turns into the safe fallback. The fallback is recorded, not hidden, so a dashboard could show "router fell back on 4% of requests" and you would know when to improve the router prompt or change the model.

## `normalize` and `extract_facts` (lines 173 to 182)

```python
def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def extract_facts(client, notes: str) -> list[dict]:
    prompt = f"<notes>\n{notes}\n</notes>\n\nList every decision, ..."
    raw = call(client, model=MODEL, system=EXTRACT_SYSTEM, prompt=prompt, schema=FACTS_SCHEMA)
    return json.loads(raw)["items"]
```

`re.sub(r"\s+", " ", text)` is a **regular expression** substitution: `\s+` means "one or more whitespace characters" (spaces, tabs, newlines), and each run becomes a single space. The `r"..."` prefix makes a **raw string** so the backslash reaches the regex engine unchanged. Normalizing matters because a quote copied from notes may wrap across a line break differently from the original.

`extract_facts` wraps the notes in `<notes>` tags so the model can tell the data apart from the instruction, asks for structured output with `FACTS_SCHEMA`, and parses the JSON with `json.loads`. It trusts the schema for shape; it does not trust the content, which is the gate's job.

## The gate: `GateResult` and `gate_facts` (lines 185 to 211)

```python
    text = normalize(notes)
    kept, rejected = [], []
    for item in items:
        quote = normalize(item.get("quote") or "")
        owner = item.get("owner")
        if not quote:
            rejected.append((item, "empty quote"))
        elif quote not in text:
            rejected.append((item, "quote not in notes"))
        elif owner is not None and normalize(owner) not in text:
            rejected.append((item, "owner not in notes"))
        else:
            kept.append(item)
    return GateResult(kept=kept, rejected=rejected)
```

This is the heart of the lab: a check written in plain code, not another model call, so it is cheap, deterministic, and testable.

- `item.get("quote") or ""` uses **dict.get**, which returns `None` instead of raising when a key is missing, and then `or ""` turns `None` into an empty string so `normalize` always gets a string.
- `kept, rejected = [], []` is **tuple unpacking**: two names assigned in one line.
- The `if / elif / else` chain checks in a fixed order and records **only the first reason**. That keeps each rejection to one clear message and makes the result predictable for the tests.
- `rejected` holds **tuples** `(item, reason)`, which is why `GateResult` annotates it as `list[tuple[dict, str]]`.

The quote check is a **substring** test on normalized text: `"Dana will deliver the revised checkout mockups by Wednesday."` is in the notes, so it passes; an invented `"the vendor is probably going to be late"` is not, so it fails.

What it cannot catch: the owner check is also a substring test, so if the model assigns "Someone should update the release checklist" to Priya Raman, who is in the attendee list, the item passes. The gate proves the name exists in the notes, not that the notes assigned the task to that person. The README calls this out; a reviewer should know the limit of every check they rely on.

## `facts_for` and `draft_update` (lines 214 to 230)

```python
def facts_for(audience: str, facts: list[dict]) -> list[dict]:
    if AUDIENCES[audience]["include_risks"]:
        return list(facts)
    return [f for f in facts if f["kind"] != "risk"]
```

The second line is a **list comprehension**: "keep each fact `f` whose kind is not risk". `list(facts)` returns a copy, so a caller that modifies the result cannot change the original list.

The design point: risks are removed **before** drafting the client update. Telling the drafter "do not mention risks" would be a prompt rule the model might break. Not giving it the risks at all is a structural guarantee. When you review code that handles sensitive data, prefer "the data never reaches the model" over "the model was asked not to repeat it".

`draft_update` builds the prompt from the audience's instructions and word limit, the verified facts as indented JSON (`json.dumps(facts, indent=2)`), and, on later rounds, a `<feedback>` block. Its docstring says it drafts "from verified facts only (never from the raw notes)": the notes never appear in this prompt, so anything the gate rejected cannot leak back in.

## `code_checks` (lines 236 to 257)

```python
    if not draft.strip():
        return ["draft is empty"]
    words = len(draft.split())
    limit = AUDIENCES[audience]["max_words"]
    if words > limit:
        problems.append(f"too long: {words} words (limit {limit})")
    for fact in facts_for(audience, facts):
        owner = fact.get("owner")
        if fact["kind"] == "action" and owner and owner not in draft:
            problems.append(f"missing owner: {owner}")
    if audience == "client":
        lowered = draft.lower()
        problems += [f"confidential term: {t}" for t in confidential_terms if t.lower() in lowered]
    return problems
```

Deterministic checks first. An empty draft returns immediately (there is nothing else to check). `draft.split()` with no argument splits on any whitespace, so the word count is the number of whitespace-separated tokens. The owner check looks only at facts this audience would see, via `facts_for`.

The confidential check lowercases both sides so "Margins" in the draft matches the term "margin". It runs only for the client, because internal readers may use the codename.

Each problem is a specific, readable sentence such as `"missing owner: Dana Whitfield"`. That matters because these strings are fed back to the drafter as feedback; a vague "failed checks" would give it nothing to fix.

Review point: the owner check is case-sensitive and exact, so a draft that writes "Dana" instead of "Dana Whitfield" fails. That is stricter than a human would be, which is the safe direction for an automated check.

## `model_review` (lines 260 to 272)

```python
    verdict = json.loads(call(client, model=EVALUATOR_MODEL, system=REVIEW_SYSTEM, prompt=prompt, schema=VERDICT_SCHEMA))
    if verdict["pass"]:
        return []
    return verdict["problems"] or ["reviewer rejected the draft without reasons"]
```

The reviewer model gets the audience, the facts, and the draft, and returns a structured verdict. The last line handles an awkward case: `pass` is `False` but `problems` is empty. Without the `or [...]` fallback, the function would return an empty list, which the loop reads as "no problems" and approves the draft the reviewer just rejected. That is a subtle bug an AI-written version can easily have, and the second refine test catches it.

## `RefineResult` and `refine` (lines 275 to 302)

```python
    audience_facts = facts_for(audience, facts)
    feedback, draft, history = "", "", []
    for round_no in range(1, max_rounds + 1):
        draft = draft_update(client, audience_facts, audience, feedback)
        problems = code_checks(draft, facts, audience, confidential_terms)
        if not problems:
            problems = model_review(client, draft, audience_facts, audience)
        history.append(problems)
        if not problems:
            return RefineResult(draft=draft, approved=True, rounds=round_no, history=history)
        feedback = "Fix these problems in your next draft:\n- " + "\n- ".join(problems)
    return RefineResult(draft=draft, approved=False, rounds=max_rounds, history=history)
```

`history: list[list[str]] = field(default_factory=list)` (line 280) gives each `RefineResult` its own fresh list. A plain `= []` default would be shared between instances, a classic Python trap, and dataclasses refuse it for that reason.

The loop is the evaluator-optimizer pattern:

- `range(1, max_rounds + 1)` counts rounds from 1, so `rounds` in the result reads naturally.
- The model review runs **only if code checks found nothing**. Paying a second model to review a draft you already know is too long would waste money, and the tests check that the reviewer is not called in that case.
- `"\n- ".join(problems)` glues the problems into a bulleted list, so the next draft's prompt says exactly what to fix.
- The loop has a hard limit. After `max_rounds`, it returns the last draft with `approved=False` instead of looping forever or pretending success. That is the human-in-the-loop handoff.

Notice that `code_checks` receives the full `facts` (it filters internally) while the drafter and reviewer receive `audience_facts`. Both are correct; a refactor that passes the wrong list to the drafter would leak risks into client drafts, which `test_client_drafts_never_see_risks` would catch.

## `StatusUpdate` and `status_update` (lines 308 to 322)

```python
    route = route_audience(client, request)
    gate = gate_facts(extract_facts(client, notes), notes)
    if not gate.kept:
        raise GateFailed(f"no supported facts; rejected: {[reason for _, reason in gate.rejected]}")
    result = refine(client, gate.kept, route.audience, confidential_terms, max_rounds)
    return StatusUpdate(route=route, gate=gate, result=result)
```

The whole workflow in five lines: route, extract, gate, stop if nothing survived, refine. Raising `GateFailed` **before** any drafting means a bad extraction never costs a draft call and never produces a confident-sounding update built on nothing. In the error message, `for _, reason in gate.rejected` unpacks each tuple and uses `_` as the conventional name for "a value I don't need".

The returned `StatusUpdate` keeps every intermediate result (route, gate, refine history), so a person can audit why the update looks the way it does.

## Running it for real (lines 325 to 338)

```python
if __name__ == "__main__":
    import anthropic
    ...
```

`if __name__ == "__main__":` runs only when you execute the file directly (`python solution.py`), not when the tests import it. The `anthropic` import lives inside this block so the offline tests never need the SDK or a key. It runs the sample notes with a client request and the confidential terms `"Bluebird"` and `"margin"`, then prints the route, what the gate rejected, and the per-round problems.

## What the tests check

- **One call** (`test_text_of_*`, `test_call_*`): thinking blocks are skipped, refusals and truncation raise `StepFailed`, and the request has exactly the expected keys, with no sampling parameters and no prefill.
- **Routing** (`test_parse_audience`, `test_route_*`): the parser accepts only cleaned exact labels; the router uses the cheap model at low effort; a hedge falls back to `team` and is marked `fell_back`.
- **The gate** (`test_gate_*`, `test_extract_*`, `test_pipeline_stops_at_the_gate_before_drafting`): whitespace differences are tolerated, each failure gets the right first reason, and the pipeline makes no draft call once the gate keeps nothing.
- **Evaluator-optimizer** (`test_code_checks_*`, `test_refine_*`, `test_client_drafts_never_see_risks`): word limits, missing owners, confidential terms only for client drafts, no paid review after a failed code check, specific feedback in the next prompt, the give-up path, and risks filtered out before the client draft.
- **End to end** (`test_status_update_end_to_end`): a leaky first draft is fixed in round 2, and the exact sequence of models called is checked.
- **Live** (`test_live_pipeline_on_sample_notes`, skipped without a key): one real run on the sample notes.

What they don't cover: whether the real models extract the right facts or write a good update (that needs evals with labeled examples), whether the reviewer model actually rejects bad drafts, and the gate's known blind spot of a real attendee being assigned an unowned task.

## Review questions

1. An AI assistant rewrites `parse_audience` as `for a in AUDIENCES: if a in raw.lower(): return a`. What goes wrong?

<details>
<summary>Answer</summary>

It returns a label whenever the label appears anywhere in the text. The hedge "Probably client, but it could be exec" would route to `client` instead of falling back to `team`, so a confused router could send internal detail outside. It also accepts "executive" as `exec`. `test_parse_audience` and `test_route_falls_back_safely_on_a_hedge` would fail.

</details>

2. Why are risks removed in `facts_for` instead of adding "never mention risks" to the client instructions?

<details>
<summary>Answer</summary>

A prompt instruction can be ignored; data the model never sees cannot be repeated. Filtering in code is a structural guarantee and is easy to test (`test_client_drafts_never_see_risks` checks the prompt itself).

</details>

3. In `refine`, what would happen if `model_review` were called on every round, even when `code_checks` found problems?

<details>
<summary>Answer</summary>

The result would be the same or similar, but every failed round would pay for an extra reviewer call, and the reviewer's problems would replace the specific code-check problems in the feedback. `test_refine_approves_after_feedback` checks the exact list of models called and would fail.

</details>

4. The model extracts "Someone should update the release checklist" with owner "Priya Raman". Does the gate keep it? Why?

<details>
<summary>Answer</summary>

Yes. The quote is in the notes and "Priya Raman" appears in the attendee line, so both substring checks pass. The gate verifies that a name exists in the notes, not that the notes assign the task to that person. That judgment needs a person, or a stronger check.

</details>

5. Why does `model_review` return `["reviewer rejected the draft without reasons"]` instead of `[]` when `pass` is false with no problems?

<details>
<summary>Answer</summary>

`refine` treats an empty list as "no problems" and approves. Returning `[]` would approve a draft the reviewer rejected. The placeholder keeps the rejection and gives the drafter (and a person reading `history`) something to see.

</details>
