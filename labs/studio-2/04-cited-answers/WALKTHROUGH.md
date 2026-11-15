# Walkthrough: cited answers you can check

## What this code does

`solution.py` asks Claude a question about a fictional travel and expense policy, hands it the retrieved policy passages, and gets back an answer with **citations**: each piece of the answer says which passage it came from and quotes the text it relied on. Then it checks those citations in plain Python, with no model involved.

The checks are mechanical and strict. Every citation must name a passage you actually sent. If it carries a position number, that position must hold the same passage. Every quote must appear word for word in that passage. Substantive text with no citation gets a warning, and the exact "I don't know" sentence is recognized as an abstention.

The same verifier also reads a second, provider-neutral citation format (`[travel-002: "exact quote"]` written inline in plain text), so you can hold any model's answers, or answers replayed from logs, to the same standard. As the README stresses, passing these checks proves the quotes are real. It does not prove the answer is right: one passage in the set is an archived FAQ that contradicts current policy, and quoting it verbatim still passes.

## How to read this lab

Open `work.py` beside this page. It starts as an exact copy of `solution.py` (made by `python lab.py review`), so the line numbers below match it until you edit it. Run the tests from VS Code's **Testing** panel (the flask icon): expand `studio-2 > 04-cited-answers` and press the run arrow. The offline tests should all pass; the two live tests are skipped unless you have an API key in `labs/.env`.

The file reads top to bottom in pipeline order: data shapes, building the request, parsing the response, verifying it, and finally the API call.

## Header, imports, and constants (lines 1 to 37)

```python
MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
...
ABSTAIN_PHRASE = "I don't know based on the provided sources."

SYSTEM_PROMPT = f"""You answer employee questions using only the search results provided in the user's message.
...
- If the search results do not contain the answer, reply with exactly: {ABSTAIN_PHRASE}
..."""
```

Settings that a reviewer might want to change live at the top as **module-level constants** (uppercase names by convention): the model, the token limit, the data path, and the prompt. That keeps them out of function bodies, where they would be easy to miss.

`SYSTEM_PROMPT` is an **f-string** in triple quotes, so it can span lines and still insert `ABSTAIN_PHRASE` with `{...}`. That insertion matters: the exact sentence the model is told to say and the exact sentence the verifier looks for (line 230) come from one constant, so they can't drift apart. If an AI edits the prompt wording and types the sentence by hand, abstention detection quietly breaks.

The prompt rules map onto what the verifier checks: use only the sources, support every factual statement, prefer the most recent policy, and abstain with the exact sentence. `SUBSTANTIVE_WORDS = 10` and the compiled regular expression `_DIGIT` (any digit) define the "worth a reviewer's look" rule used later. `re.compile` builds the pattern once so it isn't rebuilt on every call. The leading underscore in `_DIGIT` signals "internal to this module".

## The data shapes (lines 43 to 89)

```python
@dataclass
class Citation:
    passage_id: str
    quote: str
    search_result_index: int | None = None


@dataclass
class Claim:
    text: str
    citations: list[Citation] = field(default_factory=list)
```

A **dataclass** is a class whose job is to hold named fields. The `@dataclass` **decorator** (the `@` line above the class) writes the `__init__` and a readable printout for you, so `Citation("travel-002", "Hotel stays...")` just works.

The six classes describe the pipeline's data: a `Passage` you sent, a `Citation` (which passage, what quote, optionally which position), a `Claim` (a piece of answer text plus its citations), a `CitedAnswer` (all the claims plus the API's `stop_reason`), and the verifier's output, a `Problem` and a `Report`.

Details worth knowing:

- `int | None = None` is a type hint meaning "an integer, or nothing", with nothing as the default. The bracket format has no position numbers, so its citations leave it as `None`.
- `field(default_factory=list)` gives each new `Claim` its **own** empty list. Writing `citations: list = []` is a classic Python bug (every object would share one list), and dataclasses refuse it with an error. If an AI-written version uses `None` and then forgets to handle it, that's a sign to look closer.
- `@property` makes `text` and `ok` look like plain fields (`answer.text`, `report.ok`) while computing them each time. `CitedAnswer.text` joins the claims back into the full answer; `Report.ok` is true when there are no problems. Warnings (`uncited`) don't affect `ok`, which is a deliberate design: a problem means a citation is wrong; a warning means a human should glance at something.
- The comment on `Problem.kind` lists the three allowed values. Plain strings are simple; the cost is that a typo like `"unknown pasage"` wouldn't be caught by Python, only by tests.

## `load_passages` (lines 92 to 94)

```python
data = json.loads(pathlib.Path(path).read_text())
return [Passage(**p) for p in data["passages"]]
```

`Passage(**p)` uses `**` to **unpack a dictionary into keyword arguments**: `{"id": "travel-001", "title": ..., "text": ...}` becomes `Passage(id="travel-001", title=..., text=...)`. That is concise, and also strict: a passage in the JSON with an extra key (say, `"date"`) would raise `TypeError`. That strictness is useful; it catches a data format change instead of silently ignoring it.

## `build_search_results` (lines 100 to 111)

```python
return [
    {
        "type": "search_result",
        "source": p.id,
        "title": p.title,
        "content": [{"type": "text", "text": p.text}],
        "citations": {"enabled": True},
    }
    for p in passages
]
```

This is a list comprehension that produces one `search_result` block per passage, in the shape the README describes. The key decision is `"source": p.id`. The API copies `source` into every citation that points at this result, so by putting your stable passage id there, every citation comes back already labeled with the id you can check against. A URL would work too; a title would not, because titles aren't guaranteed unique.

Each passage's text goes in as one text block. The README notes that the text block is the smallest unit Claude can cite, so here a citation's `cited_text` is the whole passage. To get sentence-level citations you'd split each passage into one block per sentence.

`"citations": {"enabled": True}` is set on every block. The README and the test both say the setting must be the same on all search results, so it's set unconditionally in the one place blocks are built.

## `build_messages` (lines 114 to 121)

```python
return [
    {
        "role": "user",
        "content": [*build_search_results(passages), {"type": "text", "text": question}],
    }
]
```

The whole request is a single user turn: all the sources, then the question last. `*build_search_results(passages)` **unpacks** the list of blocks into the surrounding list, so the content is one flat list rather than a list nested inside a list.

Why this order: the docstring specifies sources first and question last, so the model reads all the material before it reads what to do with it, and `test_sources_first_question_last_single_user_turn` pins that layout. There is no assistant prefill (no partial assistant message to steer the reply), as the docstring says.

## `_get` (lines 127 to 131)

```python
def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
```

Responses reach the parser in two forms: SDK objects, whose fields you read as attributes (`block.type`), and plain dictionaries from JSON fixtures or logs (`block["type"]`). `_get` hides that difference. `isinstance` checks the type; `dict.get` and `getattr` both take a default, so a missing field returns `None` instead of raising.

This small helper is why the same parser runs on live responses, on the JSON fixtures, and on the `SimpleNamespace` objects the tests build. Without it you'd need two parsers that could disagree.

## `parse_claude_response` (lines 134 to 157)

```python
for block in _get(response, "content", []) or []:
    if _get(block, "type") != "text":
        continue
    citations = []
    for c in _get(block, "citations") or []:
        if _get(c, "type") != "search_result_location":
            continue
        citations.append(Citation(passage_id=_get(c, "source"), quote=_get(c, "cited_text") or "", ...))
    claims.append(Claim(text=_get(block, "text") or "", citations=citations))
```

A cited answer comes back as several `text` blocks; each becomes one `Claim`. In the "ok" fixture, the answer "Usually not. Room upgrades are not reimbursable unless..." arrives as four text blocks, two with citations and two connective pieces ("Usually not. " and ", and in that case you must ") with `citations: null`.

Constructs and choices:

- `x or []` turns `None` into an empty list, so the loop runs zero times instead of crashing on `for c in None`. The fixtures have `"citations": null` on uncited blocks, so this is not hypothetical.
- `continue` skips to the next loop item. It's used twice: to skip non-text blocks (the README notes a `thinking` block can appear first) and to ignore citation types other than `search_result_location`. The SDK test includes a `char_location` citation to prove it's dropped.
- `_get(c, "cited_text") or ""` makes a missing quote an empty string, which the verifier will then reject (an empty quote is never verified).
- The `stop_reason` is carried along, so callers can see why generation stopped.

What to check in an AI version: that it keeps uncited text blocks as claims instead of dropping them. Dropping them would make `answer.text` lose words, and the uncited-text warning would never fire.

## `_MARKER` and `parse_marked_answer` (lines 160 to 176)

```python
_MARKER = re.compile(r'\[(?P<id>[A-Za-z0-9_-]+):\s*"(?P<quote>[^"]*)"\]')
...
citations = [Citation(passage_id=m["id"], quote=m["quote"]) for m in _MARKER.finditer(line)]
claim_text = " ".join(_MARKER.sub("", line).split())
```

This parses the provider-neutral format, where the model writes markers like `[travel-002: "exact quote"]` into plain text. Read the regular expression in pieces:

- `\[` and `\]` are literal square brackets (escaped because brackets mean something in regex).
- `(?P<id>[A-Za-z0-9_-]+)` is a **named group** called `id`: letters, digits, underscore, or hyphen.
- `:\s*"` is a colon, optional whitespace, and an opening quote.
- `(?P<quote>[^"]*)` captures everything up to the next double quote. `[^"]` means "any character except a quote".

`finditer` yields every match on the line, and `m["id"]` reads a named group. `_MARKER.sub("", line)` deletes the markers, and `" ".join(text.split())` collapses leftover runs of spaces, so the first line of `marked_answer.txt` becomes "Business class is allowed on flights over 4 hours without approval."

Each non-empty line is one claim. Limits a reviewer should know: a quote containing a double quote character can't be expressed, and a model that splits one sentence across two lines produces two claims. Those are acceptable for a format you control through the prompt, but they are the first places to look if parsing goes wrong.

## `normalize` and `is_substantive` (lines 182 to 189)

```python
return " ".join(text.split())
...
return len(words) >= SUBSTANTIVE_WORDS or bool(_DIGIT.search(text))
```

`text.split()` with no argument splits on any run of whitespace (spaces, tabs, newlines) and drops empty pieces; joining with single spaces gives a canonical form. Quote matching uses it on both sides, so a quote broken across lines in a log still matches the passage. The test `test_quote_matching_survives_line_breaks` checks exactly that.

Note what normalization does **not** do: it doesn't lowercase, strip punctuation, or fix typos. "Economy class is default" against a passage that says "Economy class is the default" fails, as it should, because a quote is supposed to be verbatim. Loosening this (say, to fuzzy matching) would make the verifier accept paraphrases presented as quotes.

`is_substantive` is the README's admittedly crude heuristic: ten or more words, or any digit. "Usually not." is fine uncited; "Meals are capped at 100 US dollars per day" is flagged because of the number.

## `verify_answer` (lines 192 to 233)

```python
by_id = {p.id: p for p in passages}
...
for i, claim in enumerate(answer.claims):
    claim_problems = 0
    for c in claim.citations:
        total_citations += 1
        passage = by_id.get(c.passage_id)
        if passage is None:
            problems.append(Problem(i, "unknown passage", c.passage_id))
            claim_problems += 1
            continue
        idx = c.search_result_index
        if idx is not None and (idx < 0 or idx >= len(passages) or passages[idx].id != c.passage_id):
            problems.append(Problem(i, "index mismatch", f"{c.passage_id} at index {idx}"))
            claim_problems += 1
            continue
        quote = normalize(c.quote)
        if not quote or quote not in normalize(passage.text):
            problems.append(Problem(i, "quote not in passage", c.quote[:80]))
            claim_problems += 1
```

This is the heart of the lab, and the docstring is its specification. Read the docstring first, then check the code against it line by line; that is exactly the review habit this course is building.

How it works:

- `by_id` is a dict comprehension that indexes the passages by id, so each lookup is direct instead of a search through the list.
- `enumerate` supplies the claim index `i`, which is how problems and warnings point back at claims.
- The three checks run **in a fixed order**, and `continue` stops at the first failure, so each citation gets at most one problem. The order is deliberate: if the passage doesn't exist, there's nothing to compare an index or a quote against.
- The index check has three parts joined with `or`. `idx < 0` matters because Python lists accept negative indexes (`passages[-1]` is the last passage), so without it an index of -1 could "match" by accident. `idx >= len(passages)` prevents an `IndexError`.
- `if not quote or ...` rejects an empty quote. The empty string is a substring of every string (`"" in "anything"` is `True`), so without this check a blank citation would always pass. `test_empty_quote_is_never_verified` exists for exactly this trap, and it is easy for AI-written code to miss.
- `c.quote[:80]` truncates long quotes in the problem detail so reports stay readable.

After the inner loop, a claim counts toward `cited_claims` only if it had citations and none failed. A claim with no citations and substantive text goes on the `uncited` warning list.

The tampered fixture exercises every branch: claim 1 cites `travel-001` at index 3 (index mismatch), claim 2's quote says upgrades **are** reimbursable (quote not in passage), claim 3 cites `travel-099` (unknown passage), and claim 4 states a 100-dollar cap with no citation (uncited warning).

**Abstention** (lines 230 to 232): the answer abstained if it contains the exact phrase **and** has no citations at all. If it abstained, the uncited list is cleared, since "I don't know" is not an unsupported claim. The "no citations" condition matters: an answer that says the phrase and then cites a passage anyway has not really abstained, and the test `test_abstain_phrase_with_citations_is_not_an_abstention` checks it.

## `AnswerFailed` and `answer_with_citations` (lines 239 to 258)

```python
response = client.messages.create(
    model=model,
    max_tokens=MAX_TOKENS,
    system=SYSTEM_PROMPT,
    messages=build_messages(question, passages),
)
if response.stop_reason in ("refusal", "max_tokens"):
    raise AnswerFailed(f"stop_reason={response.stop_reason}")
return parse_claude_response(response)
```

`AnswerFailed` is a **custom exception**: a class that inherits from `Exception` so callers can catch this specific failure with `except AnswerFailed`. The body is just a docstring, which is enough.

The function takes `client` as an argument instead of creating one. That's **dependency injection**: the tests pass a `FakeClient` whose `create` records the call and returns a fixture, so the call shape is tested with no network and no key. The fake's `parse` method raises an error on purpose, to catch a version that uses structured outputs.

What is deliberately **not** in the call, per the docstring and README: no `output_config.format` (the README says structured outputs with citations return a 400, which is why this uses `messages.create`), and no `temperature`, `top_p`, or `top_k` (the docstring says sampling parameters are rejected on the current API version). The test checks all of these are absent. When an AI "improves" this function by adding `temperature=0` for determinism, that test is what catches it.

A `refusal` or `max_tokens` stop means the answer is missing or cut off, so the function raises instead of returning a half answer that might verify cleanly.

## `print_answer` and `main` (lines 261 to 286)

```python
flag = " [UNCITED]" if i in report.uncited else ""
print(f"{claim.text}{f' [{tags}]' if tags else ''}{flag}", end="")
```

`print_answer` reprints the answer with the cited passage ids in brackets after each claim and an `[UNCITED]` flag where the verifier warned, then lists problems. The inner f-string with a conditional adds the tags only when there are some. `end=""` stops `print` from adding a newline, so the claims run together as the original sentence did.

`main` creates the real `anthropic.Anthropic()` client (it needs the API key described in the README) and asks three questions: one answerable, one that touches the contradictory archived FAQ, and one the passages can't answer. It runs only under `if __name__ == "__main__":`, so importing the module in tests never makes an API call.

## What the tests check

- **The request** (four tests): one `search_result` per passage with the id as `source`, citations enabled on all of them, sources first and the question last in one user turn, and a system prompt that says "only" and contains the exact abstention phrase.
- **Parsing** (three tests): the "ok" fixture gives four claims with the thinking block skipped; SDK-style objects parse too and non-`search_result_location` citations are dropped; the bracket format is parsed into claims with markers removed.
- **Verification** (seven tests): whitespace normalization; the clean fixture verifies with no problems or warnings; the tampered fixture yields exactly the three problem kinds and the one warning in order; the bracket answer flags the paraphrased quote but **not** the outdated FAQ; empty quotes fail; line breaks in quotes are tolerated; abstention is recognized, and the phrase plus a citation is not an abstention.
- **The call, with a fake client** (two tests, one parametrized): exact arguments, no banned parameters, no structured-output format, and `AnswerFailed` for `refusal` and `max_tokens`.
- **Live** (two tests, skipped without a key): a real answer about hotel upgrades cites `travel-002` and verifies; an unanswerable question verifies cleanly.

What they don't check: whether a cited quote actually **supports** the claim it's attached to (a real but irrelevant quote passes), whether a source is outdated, how often the substantive heuristic is right, or the quality of the model's wording. The README is explicit that support checking needs a model or a person.

## Review questions

1. An AI simplifies the quote check to `if normalize(c.quote) not in normalize(passage.text):`. Which test fails, and why does it matter in practice?

<details>
<summary>Answer</summary>

`test_empty_quote_is_never_verified` fails. The empty string is a substring of every string, so a citation with a blank or whitespace-only quote would pass verification. In practice that means a citation that names a real passage but quotes nothing gets counted as verified, which is exactly the kind of hollow citation the verifier exists to catch.

</details>

2. Why is the index check written as `idx < 0 or idx >= len(passages) or passages[idx].id != c.passage_id`, and what goes wrong if you drop `idx < 0`?

<details>
<summary>Answer</summary>

The bounds checks run first so `passages[idx]` can't raise `IndexError` (the `or` stops at the first true condition). Without `idx < 0`, Python's negative indexing kicks in: `passages[-1]` is the last passage, so a citation to `faq-020` at index -1 would pass the check even though -1 is not a real position. The code would be accepting a malformed citation by coincidence.

</details>

3. The marked answer's first line quotes the archived 2023 FAQ word for word and passes verification. Is that a bug in `verify_answer`?

<details>
<summary>Answer</summary>

No. The verifier's job is mechanical: the passage exists and the quote is in it. Both are true. The answer is still wrong because the source is outdated, which is a data problem, not a citation problem. The fixes are upstream (drop or demote archived documents at ingestion, carry dates as metadata) or an extra warning like the one CHANGE.md adds. A good review distinguishes "this check is broken" from "this check was never meant to catch that".

</details>

4. An AI adds `temperature=0` to the `messages.create` call "so answers are reproducible". What happens, and what does the lab's code say about it?

<details>
<summary>Answer</summary>

`test_call_shape` fails, because it asserts `temperature` is not sent. The function's docstring says sampling parameters are rejected on the current API version, so the live call would fail too. The lesson for review: a change that sounds like good practice can conflict with the documented constraints of the API you're on. Check the docstring and the tests before accepting it.

</details>

5. `SYSTEM_PROMPT` inserts `ABSTAIN_PHRASE` with an f-string instead of typing the sentence out. Why?

<details>
<summary>Answer</summary>

The model is told to say exactly that sentence, and `verify_answer` looks for exactly that sentence. Defining it once means the two can't drift apart. If someone edited the prompt to say "I do not know based on the provided sources." by hand, every abstention would stop being recognized, and no error would point at the cause.

</details>
