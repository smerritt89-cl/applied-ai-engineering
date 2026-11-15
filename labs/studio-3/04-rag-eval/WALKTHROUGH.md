# Walkthrough: evaluating a RAG system and writing the report

## What this code does

`solution.py` scores a small retrieval-augmented generation (RAG) system: one that retrieves passages from a company
handbook and then writes an answer from them. It scores the two halves separately. **Retrieval** is checked against
hand-labeled relevant passages (recall@k, precision@k, MRR). **Generation** is checked for **faithfulness**: each
answer is split into claims, a judge decides whether each claim is supported by the retrieved passages, and the
answer's score is the fraction supported.

Then it checks the checker. The judge's verdicts are compared with a domain expert's labels (TPR and TNR, from week 2),
the mean faithfulness gets a bootstrap interval (week 3), and everything is formatted as a one-page Markdown report with
the plain-language bottom line first.

The judge comes in two interchangeable forms: a **live** judge that calls Claude with structured outputs, and a
**recorded** judge that replays saved verdicts so the offline tests are free and deterministic. The rest of the code
doesn't know or care which one it has. That separation is the most important design idea in the file.

## How to read this lab

Open `work.py` beside this page. It starts as a copy of `solution.py`, so the line numbers below match it until you
change something. Run the tests from VS Code's **Testing** panel (the flask icon): expand `studio-3`, then
`04-rag-eval`, and press the run button. The offline tests should all pass; the one `live` test is skipped unless you
have an API key in `labs/.env`.

Keep `fixtures/rag_outputs.json` open too. Most worked values below come from its eight questions.

## The header, imports, and judge prompt (lines 1 to 38)

```python
import anthropic
from pydantic import BaseModel, ConfigDict, Field

JUDGE_MODEL = "claude-opus-5-5"
MAX_TOKENS = 4000

JUDGE_SYSTEM = """You check whether a single claim is supported by retrieved passages from a company handbook.
...
Write a one-sentence reason first, then the verdict."""
```

The docstring (lines 1 to 13) draws the pipeline as an arrow diagram and shows both ways to run the file. Read it
first: it is the map for everything below.

Two imports are not standard library: `anthropic`, the official SDK, used only by the live judge, and `pydantic`, used
to define the shape of the judge's answer. `from dataclasses import dataclass` (line 22) is used for `LiveJudge`.

Lines 27 to 30 are **module-level constants** in capitals, a Python convention for "set once, don't reassign".
`FIXTURES = HERE / "fixtures"` uses `pathlib`'s `/` operator to join paths, and `HERE` is the folder this file lives
in, so the fixtures load no matter which directory you run from.

`JUDGE_SYSTEM` (lines 32 to 38) is the judge's system prompt, a **triple-quoted string** so it can span lines. Notice
how strict it is: a claim that adds "a number, a condition, a promise, or a permission" is not supported, and silence
means unsupported. Lenient judges are the common failure, so the prompt spells out the cases a judge tends to wave
through. It also asks for the reason before the verdict, which matches the field order in `Verdict` below.

## `recall_at_k` (lines 44 to 50)

```python
if not relevant:
    raise ValueError("recall is undefined when there are no relevant items")
top = set(retrieved[:k])
return sum(1 for r in set(relevant) if r in top) / len(set(relevant))
```

Recall@k asks: of the passages that would answer this question, what fraction made it into the top k? `retrieved[:k]`
is a **slice**, the first k ids (or all of them if fewer came back). Turning both lists into **sets** does two jobs:
membership checks are fast, and duplicate ids in the labels are counted once (`test_recall_ignores_duplicate_relevant_ids`).

The empty-relevant guard matters. With no relevant passages, the fraction is 0 divided by 0. Returning 1.0 ("found
everything, of nothing") would quietly inflate the average; raising forces whoever built the dataset to decide what
that question is for. An AI-written version often returns 0.0 or 1.0 here to "be safe", which is exactly the silent
choice this guard prevents.

Worked value: q3's only relevant chunk, `it-1`, is at rank 4. Recall@3 is 0, recall@5 is 1. That is why the fixture's
recall@3 (0.69) is lower than its recall@5 (0.81).

## `precision_at_k` (lines 53 to 56)

```python
rel = set(relevant)
return sum(1 for doc in retrieved[:k] if doc in rel) / k
```

Precision@k is the fraction of the k slots filled by relevant passages. It always divides by `k`, not by how many
items came back. If the retriever returns one correct passage when you asked for five, precision@5 is 0.2, because the
other four slots were wasted. Dividing by `len(retrieved[:k])` instead would score that as 1.0, and
`test_precision_divides_by_k` catches it.

## `reciprocal_rank` (lines 59 to 65)

```python
for rank, doc in enumerate(retrieved, start=1):
    if doc in rel:
        return 1 / rank
return 0.0
```

**`enumerate(..., start=1)`** yields pairs of (position, item), numbered from 1 instead of Python's default 0, which
matches how people talk about rank. The loop returns at the **first** relevant passage: rank 1 gives 1.0, rank 3 gives
0.33, and none at all gives 0.0. Averaged over questions this is MRR, which rewards putting the right passage near the
top, where the model is most likely to use it.

## `retrieval_metrics` (lines 68 to 75)

```python
out: dict[str, float] = {}
for k in ks:
    out[f"recall@{k}"] = statistics.fmean(recall_at_k(c["retrieved"], c["relevant"], k) for c in cases)
    ...
out["mrr"] = statistics.fmean(reciprocal_rank(c["retrieved"], c["relevant"]) for c in cases)
```

This averages each metric over all cases. `ks: tuple[int, ...] = (3, 5)` is a **type hint** for "a tuple of any
number of ints", with a default. Using a tuple (which can't be modified) rather than a list as a default argument
avoids Python's shared-mutable-default trap. `statistics.fmean` is a fast float mean that accepts a **generator
expression** directly. The keys are built with **f-strings**, so `ks=(3, 5)` produces `recall@3`, `precision@3`,
`recall@5`, `precision@5`, and `mrr`.

## The regular expressions and `split_claims` (lines 80 to 91)

```python
CITATION = re.compile(r"\s*\[[^\]]+\]")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

text = CITATION.sub("", answer)
parts = [p.strip() for p in SENTENCE_END.split(text)]
return [p for p in parts if p and len(p.split()) >= 3]
```

`re.compile` builds a reusable **regular expression**. The `r"..."` prefix is a **raw string**, so backslashes reach
the regex engine untouched.

- `CITATION` matches optional whitespace, a `[`, one or more characters that are not `]`, and a `]`. It removes
  markers like ` [pto-2]` or ` [pto-3, rem-1]` along with the space before them, so "ahead [pto-3]." becomes "ahead.".
- `SENTENCE_END` uses a **lookbehind**, `(?<=[.!?])`: "a position right after a period, exclamation mark, or question
  mark", followed by whitespace. Splitting there keeps the punctuation on the sentence. Because it requires whitespace
  after the period, `$60.50` is not split (`test_split_claims_does_not_split_inside_numbers`).

Line 90 is a **list comprehension** that strips each piece, and line 91 filters out empty pieces and fragments under
three words. `p.split()` with no argument splits on any whitespace. That drops "Yes." from q8's answer, which is a
verdict, not a checkable claim.

This splitter is deliberately simple, and the recorded judgments are keyed by its exact output. If an AI "improves"
it (say, by also splitting on semicolons), every lookup in `RecordedJudge` breaks, which is what
`test_recorded_judge_matches_your_claims` is there to catch. A real system might use a model to extract claims; then
the claim extractor itself needs evaluating.

## `faithfulness` (lines 94 to 105)

```python
if case.get("abstained"):
    return None
claims = split_claims(case["answer"])
if not claims:
    return None
contexts = [chunks[c] for c in case["retrieved"]]
supported = sum(1 for claim in claims if judge(case["id"], claim, contexts))
return supported / len(claims)
```

The return type `float | None` says "a number, or nothing". Returning `None` for an abstention is a design decision
with real consequences. An answer that says "I don't know" has no unsupported claims, so a naive score would be 1.0,
perfect faithfulness. Counting abstentions that way would let a system raise its score by refusing more. Returning
`None` keeps them out of the mean so they can be reported separately. The abstention check also comes first, so you
don't pay a judge to grade "I don't know" (`test_abstention_is_not_scored_and_not_judged`).

`judge` is a parameter, not a fixed function. Anything callable as `judge(case_id, claim, contexts)` and returning a
bool will do: the live judge, the recorded judge, or a test's scripted fake. This is **dependency injection**, the same
pattern as passing a fake client into a function, and it is why this function can be tested without an API key.

`contexts` maps ids to chunk **texts**, in retrieval rank order. Passing the ids instead would give the judge nothing
to check against; the first faithfulness test asserts the texts and the order.

## `judge_agreement` (lines 111 to 123)

```python
pos = [j for j, h in zip(judge_labels, human_labels) if h]
neg = [j for j, h in zip(judge_labels, human_labels) if not h]
if not pos or not neg:
    raise ValueError("need human labels of both classes to estimate TPR and TNR")
return {"tpr": sum(pos) / len(pos), "tnr": sum(1 for j in neg if not j) / len(neg), "n": len(human_labels)}
```

`zip` walks the two lists in step, pairing each judge verdict with the human label for the same claim. The length
check on line 117 runs first, because `zip` silently stops at the shorter list and would hide a misalignment.

`pos` holds the judge's verdicts on claims the human marked supported, and `neg` on claims the human marked
unsupported. `sum(pos)` works because Python treats `True` as 1. TPR is how often the judge accepts a truly supported
claim; TNR is how often it catches an unsupported one. On the fixtures: TPR 1.00 and TNR 0.50 over 16 claims. The
judge catches only half of the invented claims, so its faithfulness score is too generous.

Requiring both classes is the same principle as the recall guard: with no unsupported claims in the labels, TNR is 0
divided by 0, and the honest answer is "not measured", not a number.

## `bootstrap_ci` (lines 129 to 141)

```python
rng = random.Random(seed)
n = len(values)
means = sorted(statistics.fmean(rng.choices(values, k=n)) for _ in range(n_resamples))
lo = means[int((alpha / 2) * (n_resamples - 1))]
hi = means[int((1 - alpha / 2) * (n_resamples - 1))]
```

A **percentile bootstrap**: resample the per-answer scores with replacement (`rng.choices(values, k=n)`), take the
mean, repeat 2000 times, sort, and read off the 2.5th and 97.5th percentiles. `random.Random(seed)` is a private,
seeded generator, so the same data always gives the same interval. On the fixtures the seven scored answers give a mean
of 0.90 with an interval of 0.81 to 1.00: wide, because seven is a small number.

Note the indexing uses `n_resamples - 1`, a slightly different convention from lab 03's bootstrap. Both are fine;
what matters is that the docstring and the tests pin one, so results are reproducible.

## `Verdict` and `JudgeFailed` (lines 147 to 157)

```python
class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(description="One sentence citing what the passages do or do not say about the claim")
    supported: bool = Field(description="true only if the passages state or directly imply the claim")


class JudgeFailed(Exception):
    """Raised when the judge produced no usable verdict."""
```

`Verdict` is a **pydantic model**: a class whose annotated fields (`reason: str`, `supported: bool`) define a schema.
The SDK's `messages.parse` call (below) uses it to constrain the judge's reply and return a validated `Verdict`
object, so the code reads `verdict.supported` instead of parsing text. `extra="forbid"` rejects any fields beyond
these two. The `Field(description=...)` strings tell the model what each field means.

Field order is a design choice, and the README explains it: `reason` comes first so the model states its evidence
before committing to a verdict.

`JudgeFailed` is a **custom exception**: a class that inherits from `Exception` and needs no body beyond its
docstring. Having a named exception lets calling code catch "the judge failed" specifically, without also catching
real bugs.

## `build_judge_messages` (lines 160 to 168)

```python
passages = "\n".join(f'<passage index="{i}">\n{text}\n</passage>' for i, text in enumerate(contexts, start=1))
```

The judge gets one user message: each passage wrapped in its own numbered `<passage>` tag, all inside `<passages>`,
then the claim in `<claim>` tags, then the question. XML-style tags keep the passages and the claim clearly separated,
so text inside a passage can't be mistaken for the claim. `"\n".join(...)` glues the passage strings together with
newlines. The f-string uses single quotes on the outside so it can contain `"` around the index.

## `judge_claim` (lines 171 to 185)

```python
response = client.messages.parse(
    model=model,
    max_tokens=MAX_TOKENS,
    system=JUDGE_SYSTEM,
    messages=build_judge_messages(claim, contexts),
    output_format=Verdict,
)
if response.stop_reason in ("refusal", "max_tokens"):
    raise JudgeFailed(f"judge stopped with {response.stop_reason}")
if response.parsed_output is None:
    raise JudgeFailed("judge returned no parsed verdict")
return response.parsed_output
```

This is the only function that talks to Claude. It calls `client.messages.parse` with `output_format=Verdict`
(structured outputs, as the README describes), and reads the validated result from `response.parsed_output`.

The `client` is a parameter, so the tests pass a fake client that records the call and returns a canned response.
That lets `test_judge_claim_uses_structured_outputs` check the exact call shape (the model, the system prompt, the
`Verdict` format, the claim and passage text in the message) with no network. It also checks that `temperature`,
`top_p`, and `top_k` are absent; the test's message notes they are rejected on the current API version.

The two checks after the call turn every "no usable answer" outcome into one named exception: a refusal, a reply cut
off at `max_tokens`, or a reply that didn't parse. The alternative, returning a default like `False`, would quietly
count a judge failure as "unsupported" and drag down faithfulness with no trace. Failing loudly is the right default
for an evaluator; what to do about the failure is the caller's decision.

## `LiveJudge` (lines 188 to 201)

```python
@dataclass
class LiveJudge:
    client: object
    model: str = JUDGE_MODEL

    def __post_init__(self):
        self.records: list[dict] = []

    def __call__(self, case_id: str, claim: str, contexts: list[str]) -> bool:
        verdict = judge_claim(self.client, claim, contexts, self.model)
        self.records.append({...})
        return verdict.supported
```

`@dataclass` is a **decorator** that writes the `__init__` method for you from the annotated fields, so
`LiveJudge(client)` or `LiveJudge(client, model="claude-haiku-5-5")` just works. `__post_init__` runs right after that
generated `__init__`; it creates the `records` list here because a mutable default in the field list would be shared
between instances.

`__call__` is the **special method** that makes an instance callable like a function: `judge(case_id, claim,
contexts)`. That is how a class with state (the client, the model, the records) fits the same `judge(...)` interface
that `faithfulness` expects. Every verdict, with its reason, is recorded so `main` can save them to
`live_judgments.json` and you can compare a live run with the recorded one.

## `RecordedJudge` (lines 204 to 219)

```python
self.lookup = {(r["case_id"], r["claim"]): r["supported"] for r in data["judgments"]}

def __call__(self, case_id: str, claim: str, contexts: list[str]) -> bool:
    try:
        return self.lookup[(case_id, claim)]
    except KeyError:
        raise KeyError(
            f"no recorded judgment for {case_id!r}: {claim!r}. "
            "Check split_claims: claims must match the recorded text exactly."
        ) from None
```

The recorded judge loads saved verdicts into a **dict comprehension** keyed by a **tuple** of (case id, claim text).
Tuples can be dictionary keys because they can't change. It has the same `__call__` signature as `LiveJudge`, so the
rest of the code can't tell them apart. It ignores `contexts`, since it already knows the answer.

The `try`/`except KeyError` block re-raises with a message that tells you what to fix. `{claim!r}` formats the claim
with `repr`, quotes included, so stray whitespace is visible. `from None` hides the original, less helpful traceback.
Note the recorded verdicts are labeled "illustrative" in the fixture: they are not real model output, and the README
says so.

## `load_fixture` and `load_human_labels` (lines 225 to 231)

Two small loaders. `load_human_labels` builds the same (case id, claim) to bool mapping as `RecordedJudge`, so judge
and human verdicts can be matched claim by claim.

## `evaluate` (lines 234 to 276)

```python
memo: dict[tuple[str, str], bool] = {}

def cached(case_id: str, claim: str, contexts: list[str]) -> bool:
    if (case_id, claim) not in memo:
        memo[(case_id, claim)] = bool(judge(case_id, claim, contexts))
    return memo[(case_id, claim)]

per_case = {c["id"]: faithfulness(c, chunks, cached) for c in cases}
scored = [v for v in per_case.values() if v is not None]
```

This is the glue that runs every metric and returns one summary dictionary.

`cached` is a **closure**: a nested function that uses `memo` and `judge` from the enclosing function. It wraps the
judge so each claim is judged once. That matters twice: a live run pays for each claim once, and the faithfulness
score and the judge-agreement check (lines 264 to 275) see the **same** verdict for the same claim. Without the memo,
a live judge could say "supported" during scoring and "unsupported" during the agreement check, and the two numbers
would describe different judgments.

Line 246 drops the `None` values so abstentions don't enter the mean. Line 248 lists questions whose relevant passages
were not all retrieved at the largest k; on the fixtures that is `q4` and `q6`. The summary keeps `n_scored` and
`n_abstained` side by side, so the report can't present the mean without saying how many answers it covers.

The agreement block (lines 264 to 275) only runs when human labels are given, skips abstentions, and pairs judge and
human verdicts claim by claim. Notice the order of `if` checks: no judge-agreement number is reported unless at least
one labeled claim was found.

One thing this function does not do: handle a `JudgeFailed`. If the live judge refuses once, the whole evaluation
stops. That is the subject of `CHANGE.md`.

## `build_report` (lines 279 to 354)

```python
if f["mean"] is not None:
    lo, hi = f["ci"]
    faith_line = f"{f['mean']:.2f} (95% CI {lo:.2f} to {hi:.2f})"
else:
    faith_line = "not available (no scored answers)"
low = [cid for cid, v in f["per_case"].items() if v is not None and v < 1.0]
...
lines += [f"| {name} | {value:.2f} |" for name, value in r.items()]
```

The report is built as a list of lines, extended section by section, and joined with newlines at the end. The
docstring is the spec: the headings and their order, what each section must say, and "two decimals everywhere".
`{value:.2f}` is the **format specifier** that does that, so recall@5 prints as 0.81, not 0.8125.

Design points worth noticing:

- The **bottom line comes first**, in plain sentences with the interval, not just the point estimate. A stakeholder who
  reads only that section still learns the number, its uncertainty, and the main weakness (retrieval).
- `faith_line` is computed once and reused in two sections, so they can't disagree.
- `lo, hi = f["ci"]` is **tuple unpacking**: the interval tuple's two values land in two names.
- The judge check adds a warning when TNR is below 0.8 (lines 341 and 342). On the fixtures it fires, because the
  judge catches only half the unsupported claims. The report states the limits of its own measurement.
- The caveats always state the sample size and that faithfulness is not correctness, the q8 lesson from the README.

What to check in an AI-written report function: that rates are rounded only for display (never before the math), that
an empty or `None` case doesn't crash it (the `else` branch and the `or 'none'` fallbacks), and that the headings match
the spec exactly, since downstream tooling or reviewers may depend on them.

## `main` (lines 357 to 382)

`argparse` gives the script two options: `--live` (a flag, `action="store_true"`, so it is `False` unless present)
and `--out`. Both judges are built behind the same name, `judge`, and `evaluate` is called the same way for either.
After a live run, the recorded verdicts and reasons are written to `live_judgments.json` so you can diff them against
the illustrative ones, or keep them as a regression fixture for later.

## What the tests check

- **Retrieval** (six tests): recall counts only the top k, ignores duplicate labels, and refuses an empty relevant set;
  precision divides by k; reciprocal rank uses the first relevant item; the fixture's metric values.
- **Claims and faithfulness** (six tests): citations stripped and short fragments dropped, no splitting inside
  `$60.50`, the fixture's exact claims, faithfulness as a fraction with chunk texts passed in rank order, abstentions
  neither scored nor judged, and every claim found in the recorded judgments.
- **Judge agreement** (two tests): TPR and TNR on a small example, and the length and both-classes guards.
- **Bootstrap** (four tests): reproducible with a seed, zero width on constant data, narrower with more data, and an
  error on an empty list.
- **Live judge with a fake client** (two tests, three cases): the exact `messages.parse` call shape, and that refusal
  and `max_tokens` raise `JudgeFailed`.
- **Evaluate and report** (four tests): the fixture summary numbers, the report's headings, order, and formatting, a
  short plain bottom line, and the "not checked" message without human labels.
- **Live** (one test, skipped offline): a real judge accepts a supported claim and rejects an invented one.

What they don't check: whether the judge is right (only the live test touches that, on two claims), what happens when
a live judge fails mid-run, whether the answers are **correct** rather than faithful, and whether eight questions are
representative. Those are the limits the report's caveats name.

## Review questions

1. An AI changes `faithfulness` so that an abstention returns `1.0` ("it made no unsupported claims"). What happens to the fixture's mean faithfulness, and why is that a problem?

<details>
<summary>Answer</summary>

q6 now counts as a perfect answer, so the mean rises from about 0.90 (seven scored answers) to about 0.92 (eight).
The bigger problem is the incentive: a system that abstains more would score better on faithfulness while helping
users less. Abstentions are their own outcome and should be counted separately, which is what `None` enables.

</details>

2. Why does `evaluate` wrap the judge in `cached` instead of calling it directly?

<details>
<summary>Answer</summary>

So each claim is judged once. A live run pays once per claim, and the faithfulness score and the judge-agreement check
use the same verdict for the same claim. A live model can give different answers on repeated calls; without the memo,
the two numbers in the report could be based on different judgments.

</details>

3. The recorded judge gives faithfulness 0.90, but the README says the human labels give about 0.76. Which part of the report warns the reader, and what number drives the warning?

<details>
<summary>Answer</summary>

The "Judge check" section. It reports TNR 0.50 (the judge caught half of the unsupported claims) and, because TNR is
below 0.8, adds the line saying faithfulness is likely overstated. A lenient judge inflates faithfulness, so the
report states its own measurement weakness.

</details>

4. `judge_claim` raises `JudgeFailed` on a refusal. Why not just return `Verdict(reason="refused", supported=False)`?

<details>
<summary>Answer</summary>

That would silently count a judge failure as an unsupported claim, lowering the answer's faithfulness for a reason
that has nothing to do with the answer, and leaving no trace in the report. A named exception makes the failure
visible and lets the caller decide what to do (retry, skip and report, or stop).

</details>

5. q8's answer gets faithfulness 1.0. Is it a good answer?

<details>
<summary>Answer</summary>

Not necessarily. It says "Yes" to "Do I need approval to take a week off?" and cites a rule about requests of more
than 5 consecutive working days. The claim it makes is supported, but for a standard five-day week the answer may be
wrong. Faithfulness measures agreement with the retrieved text, not correctness; catching this needs a reference
answer and a correctness grader.

</details>
