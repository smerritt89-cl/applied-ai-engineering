# Walkthrough: Lab 02, build a supervised fine-tuning dataset

## What this code does

This lab turns 50 labeled business documents into a dataset you could fine-tune on and a test set you could
report a number from. The task is the action-item extraction from Studio 1: each label is a list of items with a
task, an owner, a deadline, a priority, and a verbatim evidence quote.

The module docstring (lines 1 to 12) lists the pipeline, and the code follows it in order: validate every gold
label, drop exact and near-duplicate documents, split into train, validation, and test (stratified by document kind
and keeping threads together), check that nothing leaks across splits, write the training files in the chat format
that fine-tuning tools accept, and freeze the test set with a fingerprint. An optional live step asks Claude to
draft labels for new documents and marks every draft as needing human review.

The design principle throughout is **quarantine, don't delete**. Bad labels and duplicates are reported with
reasons, so a person can fix them and the next build picks them back up. And every function is deterministic
(the split uses a fixed seed), so the same input always produces the same dataset, which is what makes the test
fingerprint meaningful.

## How to read this lab

Open `work.py` in VS Code beside this page. It starts as a copy of `solution.py`, so the line numbers below match
it until you edit it. Read a section here, then the same lines there.

Run the tests from VS Code's **Testing** panel (the flask icon): expand `studio-5/02-sft-dataset` and press run.
The offline tests should all pass; the one live test is skipped without an API key. From a terminal, the same
thing is `pytest studio-5/02-sft-dataset -q` from the `labs` folder. To see the whole build, run
`python studio-5/02-sft-dataset/work.py`.

## Imports and settings (lines 13 to 42)

```python
import pydantic
from pydantic import BaseModel, ConfigDict, Field, model_validator

SPLITS = ("train", "val", "test")
DEFAULT_FRACTIONS = {"train": 0.7, "val": 0.15, "test": 0.15}
NEAR_DUP_THRESHOLD = 0.7
SHINGLE_SIZE = 5
CHARS_PER_TOKEN = 4  # rough estimate for English; use the real tokenizer before a training run
```

Most imports are from the standard library: `hashlib` for the fingerprint, `random` for a seeded shuffle,
`collections.defaultdict` for grouping, and `dataclasses` for the build report. The one third-party library is
**Pydantic**, which validates data against a schema written as Python classes.

The settings at the top are the decisions a reviewer should look at first: the split fractions, the near-duplicate
threshold, the shingle size, and a crude characters-per-token estimate. The comment on `CHARS_PER_TOKEN` is honest
about what it is. The `SYSTEM_PROMPT` (lines 34 to 36) is the instruction every training example will carry; it is
part of the training data, so changing it later means rebuilding the dataset.

## The label schema: `ActionItem` and `Extraction` (lines 48 to 70)

```python
class ActionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=3, description="What will be done, as a short imperative phrase")
    owner: str | None = Field(description="Name of the person responsible, as written; null if no person is named")
    ...
    priority: Literal["high", "medium", "low"] = Field(description="Urgency signaled by the document")
    evidence: str = Field(min_length=10, description="A verbatim quote from the document that shows the item")

    @model_validator(mode="after")
    def _owner_or_reason(self) -> "ActionItem":
        if self.owner is None and not (self.owner_missing_reason or "").strip():
            raise ValueError("owner_missing_reason is required when owner is null")
        return self
```

A Pydantic **model** is a class whose fields have **type hints** (`str | None` means "a string or None") and
optional constraints. `Field(min_length=3, ...)` adds a rule, and `description` documents the field (it is also
what a structured-output call shows the model). `Literal["high", "medium", "low"]` allows only those three strings.
`due_date: date | None` makes Pydantic parse an ISO string like `"2026-11-20"` into a real date and reject anything
else. `extra="forbid"` rejects unknown keys, so a typo like `"ownr"` is an error rather than silently ignored.

`@model_validator(mode="after")` is a **decorator** that registers an extra check to run after the fields are
validated. It enforces a rule that involves two fields at once: if there is no owner, there must be a reason. That
is the planted error in record `t12`.

`Extraction` wraps a list of items. An empty list is valid on purpose: eight documents have no action items, and a
model that never sees an empty answer learns to invent items.

## `load_jsonl` (lines 76 to 78)

```python
with open(path, encoding="utf-8") as f:
    return [json.loads(line) for line in f if line.strip()]
```

The **`with` statement** opens the file and guarantees it is closed afterwards, even if an error occurs. Looping
over a file gives one line at a time, and the **list comprehension** parses each non-blank line as JSON. Passing
`encoding="utf-8"` explicitly avoids surprises on machines whose default encoding differs.

## Validating gold labels: `normalize_ws` and `validate_record` (lines 84 to 116)

```python
def normalize_ws(text: str) -> str:
    return " ".join(text.split())

    try:
        extraction = Extraction.model_validate(record["label"])
    except pydantic.ValidationError as err:
        for e in err.errors():
            where = ".".join(str(p) for p in e["loc"]) or "(root)"
            problems.append(f"schema: {where}: {e['msg']}")
        return problems
    source = normalize_ws(record["text"])
    for i, item in enumerate(extraction.items):
        quote = normalize_ws(item.evidence)
        if not quote or quote not in source:
            problems.append(f"item {i}: evidence not found in source")
        if item.owner is not None and normalize_ws(item.owner) not in source:
            problems.append(f"item {i}: owner not found in source")
```

`normalize_ws` (lines 84 to 86) collapses every run of whitespace to one space, so a quote still matches when the
document wraps a line differently.

`validate_record` (lines 89 to 116) returns a list of problems, empty when the record is usable. The docstring fixes
the order. Reading it:

- A label with `label_status == "needs_review"` is flagged first. That is the guard that keeps a model-drafted label
  from slipping into training as if a person had checked it.
- `Extraction.model_validate(...)` runs the schema inside **try/except**. On failure, Pydantic's `err.errors()`
  gives one entry per problem with a `loc` (location) such as `("items", 0, "priority")`. The
  **generator expression** joins it into `items.0.priority`, so the message says exactly where the problem is.
  The function then **returns early**: checking evidence on a malformed label would produce noise.
- For each item, the evidence must be an **exact substring** of the source after whitespace normalization. Exact
  matching is strict on purpose. A paraphrased quote (`e12`) is the most common labeling error, and it teaches the
  model to paraphrase while claiming to quote.
- If an owner is named, it must appear in the text. That catches `m12`, where the labeler named someone the
  document never mentions.

`enumerate(extraction.items)` numbers the items from 0, which is how the messages say `item 0`. When you review an
AI-written validator, check that it compares the same normalized form on both sides; normalizing only one side is
an easy mistake that makes every multi-line quote fail.

## Near-duplicate detection (lines 122 to 169)

```python
def normalize_for_dedup(text: str) -> str:
    return normalize_ws(re.sub(r"[^\w\s']", " ", text.lower()))

def shingles(text: str, k: int = SHINGLE_SIZE) -> set[str]:
    words = normalize_for_dedup(text).split()
    ...
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}

def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)
```

`normalize_for_dedup` (lines 122 to 125) lowercases the text and replaces punctuation with spaces using a
**regular expression**: `[^\w\s']` means "any character that is not a word character, whitespace, or an
apostrophe". The `r` prefix makes it a **raw string** so the backslashes reach the regex engine unchanged.

`shingles` (lines 128 to 136) turns the text into the **set** of every run of five consecutive words, built with a
**set comprehension** (curly braces). Sets drop repeats and make comparison easy. Short texts get one shingle of all
their words so they can still be compared.

`jaccard` (lines 139 to 143) is the size of the intersection (`&`) over the size of the union (`|`): 1.0 for
identical sets, 0.0 for nothing shared. The guard avoids dividing by zero when both sets are empty.

```python
    for r in records:
        s = shingles(r["text"])
        best_j, best_id = 0.0, None
        for other, other_s in zip(kept, kept_shingles):
            j = jaccard(s, other_s)
            if j > best_j:
                best_j, best_id = j, other["id"]
        if best_id is not None and best_j >= threshold:
            dropped.append({"id": r["id"], "duplicate_of": best_id, "jaccard": round(best_j, 3)})
        else:
            kept.append(r)
            kept_shingles.append(s)
```

`dedupe` (lines 146 to 169) walks the records in order and compares each one only with records already **kept**.
That makes "keep the first of each cluster" automatic: the original arrives first and is kept, and the copy is
dropped. `kept_shingles` is a parallel list so each kept record's shingles are computed once, and
`zip(kept, kept_shingles)` walks the two lists together.

It tracks the **best** match, not just the first one over the threshold, so the report names the closest original.
`round(best_j, 3)` keeps the report readable. On the shipped data it drops `e05-reexport` (similarity 1.0, an exact
re-export), `t07-fwd` (0.885, a forwarded ticket with a header added), and `m03-v2` (0.761, a lightly edited note).

The threshold of 0.7 works here because the planted duplicates sit far above every other pair. The README is
explicit that real data is rarely that clean: compute the similarities, sort them, and read the pairs near your
threshold before trusting it.

## The split: `stratified_group_split` (lines 175 to 224)

```python
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[r[group_key]].append(r)
    ...
        kinds = {m[strata_key] for m in members}
        if len(kinds) != 1:
            raise ValueError(f"group {gid} mixes strata: {sorted(kinds)}")
    ...
    rng = random.Random(seed)
    for stratum in sorted(strata):
        gids = sorted(strata[stratum])
        rng.shuffle(gids)
        ...
        for gid in gids:
            for split in ("test", "val"):
                if counts[split] < targets[split]:
                    assignment[gid] = split
                    counts[split] += len(groups[gid])
                    break
            else:
                assignment[gid] = "train"
```

Two constraints shape the split. **Group-aware**: every record in a thread goes to the same split, because an email
and its reply in different splits would let the model see part of a test answer. **Stratified**: each document kind
(email, ticket, meeting, chat) appears in every split in roughly the target proportions, so the test set reflects
the mix you train on.

- `defaultdict(list)` is a dictionary that creates an empty list the first time you use a new key, which makes
  grouping a two-line loop.
- `{m[strata_key] for m in members}` is the set of kinds in one group. More than one means the data is inconsistent,
  and the function raises rather than guessing.
- `random.Random(seed)` is a **seeded random generator**: the same seed always produces the same shuffle. Sorting
  before shuffling matters too. Dictionary order depends on input order, so sorting first makes the result depend
  only on the seed and the data, not on how the file happened to be ordered.
- The fill loop gives whole groups to `test` until it reaches its target, then to `val`, then the rest to `train`.
  The inner `for ... else` is a less common Python construct: the `else` block runs only if the loop finished
  **without** a `break`, which here means "neither test nor val needed this group".

`round(n * fractions["test"])` sets the target in records, and because whole groups are added, a split can overshoot
slightly. Expect sizes close to the fractions, not exact. On the shipped data each kind of 11 documents splits 7, 2,
2, giving 28, 8, and 8 overall.

The final loop (lines 221 to 223) builds the output by walking the records in their **original order**, so each
split keeps input order regardless of the shuffle. A test checks this, because a stable order is what makes the
written files reproducible.

## `check_split_leakage` (lines 227 to 249)

```python
    cache = {r["id"]: shingles(r["text"]) for s in names for r in splits[s]}
    for i, sa in enumerate(names):
        for sb in names[i + 1 :]:
            for ra in splits[sa]:
                for rb in splits[sb]:
                    if ra.get(group_key) is not None and ra.get(group_key) == rb.get(group_key):
                        reason = "same group"
                    elif jaccard(cache[ra["id"]], cache[rb["id"]]) >= threshold:
                        reason = "near-duplicate"
                    else:
                        continue
```

This is the audit after the split: it compares every record in one split with every record in each **later** split
(`names[i + 1 :]` is a slice of the splits after this one, so each pair of splits is checked once).

`cache` is a **dictionary comprehension** with two `for` clauses, computing every record's shingles once up front
instead of once per comparison. `ra.get(group_key) is not None` stops two records that both lack a thread from being
reported as the "same group". The `if`/`elif`/`else: continue` reports each pair once with the most specific reason.

Why check again after a group-aware split? Because the split only knows about threads. The forwarded ticket
`t07-fwd` lives in a different thread from `t07`, so only content comparison catches it. On the real build it was
already removed by `dedupe`, and a test confirms the final leakage list is empty.

Comparing every pair is fine for 44 records and hopeless for millions; at scale you would use MinHash and
locality-sensitive hashing (lesson 6).

## Chat-format examples: `user_message` and `to_chat_example` (lines 255 to 275)

```python
def user_message(text: str) -> str:
    return f"<document>\n{text}\n</document>\n\nExtract the action items from this document."

            {"role": "assistant", "content": json.dumps(record["label"], ensure_ascii=False, sort_keys=True)},
```

Each training example is a `messages` list with a system turn, a user turn, and the assistant turn the model should
learn to produce. This is the format OpenAI's fine-tuning API and TRL's `SFTTrainer` both accept.

`user_message` wraps the document in tags with an **f-string**. It is its own function because the exact same
wording must be used for training, for drafting labels, and later at inference; a mismatch between training and
production prompts is a quiet way to lose accuracy.

`json.dumps(..., sort_keys=True)` writes the label with keys in alphabetical order, so identical labels always
produce identical text (which is what lets duplicate detection work), and `ensure_ascii=False` keeps names like
"José" readable instead of escaping them. Nothing else goes in the example: no ids, no metadata. Anything you put in
the training text, the model learns to produce.

## `validate_chat_lines` (lines 278 to 341)

```python
        structural = None
        for i, m in enumerate(msgs):
            role = m.get("role") if isinstance(m, dict) else None
            if role not in ("system", "user", "assistant"):
                structural = f"unknown role {role}"
                break
            ...
        if structural:
            problems.append((n, structural))
            continue

        total_chars = sum(len(m["content"]) for m in msgs)
        if total_chars // CHARS_PER_TOKEN > max_tokens:
            ...
        try:
            Extraction.model_validate_json(answer)
        except pydantic.ValidationError:
            problems.append((n, "assistant output fails schema"))
        if any(m["role"] != "assistant" and answer.strip() in m["content"] for m in msgs[:-1]):
            problems.append((n, "label leaked into prompt"))
        key = json.dumps(msgs, sort_keys=True, ensure_ascii=False)
```

This checks the written JSONL the way a training job would, then adds checks a job won't do. It works in two phases:

- **Structural** checks (lines 299 to 324) stop at the first failure per line, using `break` out of the message loop
  and `continue` to the next line. A line that is not a valid conversation can't be judged further.
- **Content** checks (lines 326 to 340) report everything that applies: an estimated length over the limit
  (`//` is floor division), an assistant answer that fails the same Pydantic schema
  (`model_validate_json` parses and validates in one step), the answer text pasted into the prompt (which would teach
  copying), and exact duplicates, compared as canonical JSON with sorted keys.

`all(t == ("user" if i % 2 == 0 else "assistant") ...)` checks that turns alternate: `i % 2` is 0 for even
positions and 1 for odd ones. The `seen` dictionary maps each canonical conversation to the first line number it
appeared on.

The length check uses the four-characters-per-token estimate. It is fine as a smoke alarm and wrong as a precise
limit; the comment at line 42 says to use the real tokenizer before a training run.

## `fingerprint` (lines 344 to 348)

```python
    ordered = sorted(records, key=lambda r: r["id"])
    return hashlib.sha256(json.dumps(ordered, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
```

A **fingerprint** is a short string that changes if anything in the test set changes. `sorted(..., key=lambda r:
r["id"])` sorts the records by id using a **lambda** (a one-line unnamed function) as the sort key, so the
fingerprint doesn't depend on order. `sort_keys=True` makes the JSON canonical. SHA-256 then reduces it to a
64-character hex digest.

The point is a **frozen test set**. You record the fingerprint when you first report a number; if it changes later,
someone edited the test set, and old and new scores are no longer comparable. That is exactly the signal you want
when a label fix touches the test split.

## The build: `BuildReport`, `build_dataset`, `write_outputs` (lines 354 to 408)

`BuildReport` (lines 354 to 372) is a **dataclass**, a decorator that turns a class with typed fields into a simple
record with an automatic constructor. `field(default_factory=dict)` gives each report its own empty dictionary (a
plain `= {}` default would be shared between instances, a classic Python bug, and dataclasses refuse it).
`summary()` formats the counts per split and kind.

`build_dataset` (lines 375 to 388) is the whole pipeline in a few lines: quarantine records with problems, dedupe the
rest, split, check leakage, fingerprint the test set. `kept, report.dropped = dedupe(clean)` is **tuple unpacking**
straight into an attribute.

`write_outputs` (lines 391 to 408) writes train and val in chat format, but writes the test set as **raw records**
(inputs plus gold labels), because the test set is for scoring, never for training. `manifest.json` lists the ids
in each split, the fingerprint, and what was quarantined and dropped. The README's advice to commit the manifest
and not the data is the practical version of this: the manifest is reviewable and safe to share.

## Optional live step: `DraftFailed` and `draft_label` (lines 414 to 446)

```python
    response = client.messages.parse(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message(record["text"])}],
        output_format=Extraction,
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        raise DraftFailed(...)
    ...
    drafted = dict(record)
    drafted["label"] = response.parsed_output.model_dump(mode="json")
    drafted["label_status"] = "needs_review"
```

`DraftFailed` is a custom **exception** class; `pass` means it adds nothing beyond its name, which is enough for a
caller to catch this specific failure.

`draft_label` asks Claude for a label using `client.messages.parse` with the Pydantic class as `output_format`, so
the reply comes back already parsed into an `Extraction`. It raises if the model refused, ran out of tokens, or
returned nothing parseable, rather than returning an empty label that would look like "no action items".

`dict(record)` makes a **shallow copy**, so the caller's record is not modified (a test checks this). The draft is
marked `needs_review` and records which model wrote it, and `draft_flags` runs the same validator, ignoring the
"not reviewed" flag, so a reviewer sees invented quotes or owners immediately. The client is passed in as an
argument, which is what lets the tests use a fake client with no network or key.

## The script (lines 452 to 466)

`main` loads the data, builds, prints the summary and each quarantined record's problems, writes the outputs, and
re-validates the written files with `validate_chat_lines`. Validating what you actually wrote, not what you meant to
write, is a cheap check that catches serialization bugs.

## What the tests check

- **Gold labels** (`test_normalize_ws` through `test_planted_label_errors_in_the_data`): a valid record and an
  empty label pass; line wrapping doesn't break evidence matching; a paraphrased quote and an unknown owner are
  caught; schema errors carry their location; drafts are not gold until reviewed; exactly the three planted errors
  are found in the data.
- **Near-duplicates** (`test_normalize_for_dedup` through `test_dedupe_finds_the_planted_duplicates`):
  normalization, shingles, Jaccard, keep-first behavior, and exactly the three planted duplicates (with the
  forwarded ticket a near, not exact, duplicate).
- **Splits and leakage** (`test_split_*`, `test_threads_never_cross_splits`, `test_leakage_*`,
  `test_clean_build_has_no_leakage`): the split is a partition, deterministic for a seed, stratified, group-safe,
  order-preserving, and refuses a mixed-kind thread; the leakage check finds both kinds of leak; the real build is
  clean.
- **Chat format** (`test_to_chat_example_shape` through `test_written_files_pass_the_validator`): the example shape,
  every structural and content problem in the validator, an order-independent but content-sensitive fingerprint,
  and written files that pass the validator.
- **Drafting** (`test_draft_label_*`): with a fake client, drafts are marked for review, don't mutate the input,
  never pass as gold, flag an invented quote, and fail loudly on refusal or truncation. One live test drafts four
  real labels for you to read.

What they don't cover: whether a label is **right** (only that it is consistent with its source), whether the
threshold of 0.7 suits other data, whether 8 test documents are enough to measure anything (they aren't, for small
differences), and the accuracy of the token estimate. Those need human judgment and more data.

## Review questions

1. Why does `validate_record` return immediately after a schema error instead of also checking evidence?

   <details><summary>Answer</summary>

   If the label doesn't match the schema, `extraction` doesn't exist, and even if it partly did, evidence findings on
   a malformed label would be noise. Reporting the schema problem with its location is the useful output; once it is
   fixed, the next build runs the content checks.

   </details>

2. `dedupe` compares each record only with records already kept, not with every other record. What behavior does
   that give you, and what would change if it compared with every record?

   <details><summary>Answer</summary>

   It keeps the first record of each cluster and drops later copies, each reported against its closest kept
   original. Comparing against every record (including dropped ones) could chain: C is similar to B, B to A, and C
   gets dropped as a duplicate of B even though B itself was dropped. Keeping only kept records in the comparison
   makes the result simple to explain.

   </details>

3. An AI assistant "simplifies" the split by shuffling individual records with `random.shuffle(records)` and slicing
   70/15/15. What breaks?

   <details><summary>Answer</summary>

   Three things. Threads can straddle splits, so related documents leak into the test set (`test_threads_never_cross_splits`
   fails). The kinds are no longer guaranteed in every split (`test_split_is_stratified_by_kind` can fail). And the
   module-level `random.shuffle` is not seeded, so the split changes every run and the test fingerprint becomes
   meaningless.

   </details>

4. The test set is written as raw records, while train and val are written in chat format. Why the difference?

   <details><summary>Answer</summary>

   Train and val are inputs to the fine-tuning job, which wants the `messages` format. The test set is for scoring: you
   need the document to prompt with and the gold label to compare against, kept separate from anything the model
   trains on. Writing it in the training format would also make it easy to accidentally include it in a training run.

   </details>

5. Your teammate drafts 200 labels with Claude and wants to set them all to `"reviewed"` in one script because
   `draft_flags` is empty for most of them. What do you say?

   <details><summary>Answer</summary>

   An empty `draft_flags` only means the draft is consistent with its document: quotes are verbatim and owners appear
   in the text. It doesn't mean the draft is right. A suggestion recorded as a commitment, a group request given one
   owner, or an invented date all pass these checks. Someone has to read each draft; whoever flips the status is the
   labeler, and the draft's errors become the model's errors.

   </details>
