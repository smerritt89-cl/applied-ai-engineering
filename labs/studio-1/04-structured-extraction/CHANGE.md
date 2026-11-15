# Change request: verify the deadline wording too

You'll make this change in `work.py` (your copy of the solution), using a coding assistant such as Claude Code. Then you review what it did before you accept it.

## The change

`verify_evidence` checks two things against the source document: the evidence quote and the owner's name. It does not check `due_phrase`, the deadline wording the model is told to copy from the document ("by end of day Thursday").

That's a gap. A model that writes `due_phrase: "by next Monday"` for a commitment the email dated "by end of day Thursday" passes every check today, and a wrong deadline is one of the most expensive mistakes an action-item tool can make.

Add a third check to `verify_evidence`: when `due_phrase` is set (not `None`), its whitespace-normalized text must appear in the whitespace-normalized source, exactly like the evidence check. If it doesn't, add the problem `"due_phrase not found in source"`. It goes after the two existing problems, so the order is evidence, owner, due phrase. A `due_phrase` of `None` is fine and is never flagged.

Nothing else changes: the schema, the prompt, the retry logic, and the existing two checks stay as they are.

## Write your prompt

Write your own prompt before you open the example. A good one for this change:

- Names the function and the file (`verify_evidence` in `work.py`).
- States the rule precisely: same normalization as the evidence check, exact match, skip when `None`.
- Gives the exact problem string and where it goes in the list, because the tests compare strings.
- Says what must **not** change, so the assistant doesn't "improve" the matching (for example by lowercasing) or touch the schema.
- Asks for the docstring to be updated to list the new problem.

## Example prompt

<details>
<summary>Show the example prompt</summary>

```text
In work.py, extend verify_evidence so it also checks due_phrase.

Rule: if item.due_phrase is not None, normalize it with the existing normalize()
function and check that it is a substring of the normalized source, exactly like
the evidence check. If it isn't, append the problem string
"due_phrase not found in source". This problem comes after the existing
"evidence not found in source" and "owner not found in source" problems.
A due_phrase of None is never flagged.

Do not change the matching rules for evidence or owner, do not lowercase or
fuzzy-match anything, and do not change the Pydantic models, the system prompt,
or extract(). Update the verify_evidence docstring to list the new problem in
the same format as the other two.

Then run: pytest studio-1/04-structured-extraction -q
```

</details>

## Review the AI's change

Before you accept the change, check:

- [ ] **Scope.** The diff touches `verify_evidence` (and its docstring) only. No edits to the models, `SYSTEM_PROMPT`, `normalize`, or `extract`.
- [ ] **Same matching rule.** The new check uses `normalize(...)` and a plain `in` test against the already-normalized source. No `.lower()`, no regular expressions, no similarity scores.
- [ ] **`None` is skipped.** The check is guarded with `item.due_phrase is not None` (or equivalent), so items without a deadline aren't flagged.
- [ ] **Exact string and order.** The problem text is exactly `due_phrase not found in source`, and it's appended after the owner check.
- [ ] **Docstring.** The list of problems in the docstring now has three entries.
- [ ] **Edge case to think about.** What happens with `due_phrase=""`? (The empty string is "in" every string, so it passes.) Decide whether that's acceptable, and if not, say so in a follow-up prompt rather than accepting a silent change.

## Check it

From the `labs` folder:

```bash
pytest studio-1/04-structured-extraction/test_change.py -q
```

All the change tests should pass. Then run the whole lab to make sure nothing else broke:

```bash
pytest studio-1/04-structured-extraction -q
```

`change_solution.py` in this folder is a reference version with the change applied, if you want to compare.
