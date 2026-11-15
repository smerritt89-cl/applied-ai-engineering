# Change: check that the deadline wording is copied from the source

## The change

`validate_record` checks that each item's evidence is a verbatim quote and that a named owner appears in the
document. It does not check `due_phrase`, even though the schema describes it as "the deadline wording copied from
the document". That gap matters most for drafted labels: a model that turns "next Tuesday" into "by November 21"
produces a deadline the document never stated, and nothing flags it.

Ask a coding assistant to add one check to `validate_record`:

- If an item's `due_phrase` is not `None` and, after `normalize_ws`, is not an exact substring of the normalized
  source text, report `"item <i>: due_phrase not found in source"`.
- It runs after the owner check for the same item, so the per-item order is evidence, owner, due phrase.
- Schema errors still stop the function before any content check, as now.

Every `due_phrase` in `data/sources.jsonl` is verbatim, so the build should quarantine exactly the same three
records as before. Because `draft_label` reuses `validate_record`, drafts with invented deadlines get flagged
automatically.

The work happens in `work.py` (your copy of the solution). The tests import it automatically while it exists.

## Write your prompt

Write your own prompt first, before opening the example. A good prompt for this change:

- names the function and the exact problem string, including the item number format;
- says where the check goes (after the owner check, inside the per-item loop) and that it uses `normalize_ws` on
  both sides, like the existing checks;
- says what must not change: the schema-error early return, the existing messages and their order, and everything
  outside `validate_record`;
- asks for the docstring to list the new problem;
- asks for tests, including a null `due_phrase`, line wrapping, several items, and a check that the shipped data
  still quarantines only `e12`, `t12`, and `m12`.

## Example prompt

<details><summary>Show the example prompt</summary>

```text
In work.py, add one content check to validate_record. Inside the per-item loop, after the owner
check, append "item {i}: due_phrase not found in source" when item.due_phrase is not None and
normalize_ws(item.due_phrase) is not a substring of the normalized source text (the same `source`
variable the evidence check uses).

Keep everything else exactly as it is: the "label not reviewed" check first, the early return
after schema errors, the evidence and owner checks and their wording, and the order of problems
(evidence, owner, then due_phrase for each item). Don't change any other function. Add the new
problem to the docstring's list.

Add tests: an invented due_phrase is reported; a due_phrase that matches only after whitespace
normalization passes; due_phrase None passes; with two items, only the bad one is reported with
its index; a schema error still returns only schema problems; and building from
data/sources.jsonl still quarantines exactly e12, t12, and m12.
```

</details>

## Review the AI's change

Read the diff before running anything. Check:

- **Scope.** Only `validate_record` (and its docstring) changed, plus tests. Watch for "while I was there" edits to
  the schema, such as making `due_phrase` required or adding a Pydantic validator; those change what counts as a
  valid label everywhere.
- **Normalization on both sides.** The due phrase is passed through `normalize_ws` and compared against the
  already-normalized `source`. Normalizing only one side makes multi-line documents fail.
- **None is allowed.** A missing deadline is legitimate and must not be flagged. Look for `is not None`, not a
  truthiness test that would behave differently for an empty string without saying so.
- **Order and wording.** The new message matches the requested string exactly and comes after the owner check;
  existing messages are unchanged (other code and tests compare them as strings).
- **The early return survives.** Schema errors still return before any content check.
- **Data unchanged.** The full build still quarantines the same three records and the test fingerprint is the same.

## Check it

From the `labs` folder:

```bash
pytest studio-5/02-sft-dataset/test_change.py -q
```

Then run the full lab to make sure nothing else broke:

```bash
pytest studio-5/02-sft-dataset -q
```

Both should pass. As a final check, run `python studio-5/02-sft-dataset/work.py` and confirm the summary still shows
3 quarantined, 3 dropped, and splits of 28, 8, and 8.
