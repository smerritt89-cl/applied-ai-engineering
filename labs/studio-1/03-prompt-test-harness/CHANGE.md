# Change: check the summary's word count

You'll make this change in `work.py` (your copy of `solution.py`), using a coding assistant
such as Claude Code. Then you'll review what it did before running the acceptance tests.

## The change

Prompt v2 tells the model to write a summary of "one sentence, under 25 words". Nothing in the
harness checks that. The closest check, `max_length`, counts **characters in the whole output**,
JSON keys and all, so a 60-word summary can slip through if the other fields are short, and a
fine summary can fail if the model adds whitespace.

You want a new check type that test cases can use:

```json
{"type": "json_field_max_words", "field": "summary", "value": 25}
```

It should pass when the named field of the JSON output is a string of at most `value` words, and
fail otherwise: when the output isn't a JSON object, when the field is missing, or when the field
isn't a string. It should accept output wrapped in a Markdown code fence, the same way the other
`json_*` checks do.

This is the "write the check for the rule you stated" habit from lesson 6: if a prompt states a
requirement, a test should measure it.

## Write your prompt

Write your own prompt first, before you open the example. A good one for this change:

- Names the function to change (`run_check`) and the exact check shape, including the field and
  value keys.
- Says what counts as a word (split on whitespace) and whether the limit is inclusive.
- Lists the failure cases: not JSON, not an object, missing field, non-string field.
- Says to reuse the existing JSON parsing (`parse_json_output`) rather than parse again.
- Says what must not change: the other check types, unknown types still raising `ValueError`,
  and the prompts.
- Asks for the docstring to be updated, and for tests.

<details>
<summary>Example prompt</summary>

```text
In work.py, add a new check type to run_check called "json_field_max_words".
Its shape is {"type": "json_field_max_words", "field": <name>, "value": <int>}.

It passes when the output parses as a JSON object (use the existing
parse_json_output, so a surrounding ```json fence is accepted) and that field
is a string with at most `value` words, counting words with str.split(). The
limit is inclusive. It fails (returns False, never raises) when the output is
not JSON, is JSON but not an object, the field is missing, or the field is not
a string.

Don't change any other check type, the prompts, or the rest of the file.
Unknown check types must still raise ValueError. Update run_check's docstring
to list the new type and its rules. Add tests for: under the limit, exactly at
the limit, one word over, a missing field, a non-string field, and fenced JSON.
```

</details>

## Review the AI's change

Read the diff before running anything. Check:

- [ ] **Scope.** Only `run_check` (and its docstring) changed. No edits to the prompts,
  `call_model`, or `cases.json` unless you asked for them.
- [ ] **Reuse.** It calls `parse_json_output` instead of adding a second `json.loads`, so fenced
  output is handled the same way everywhere.
- [ ] **Type safety.** A field that is `None`, a number, or a list returns `False`. Watch for
  `len(value.split())` on a non-string, which raises `AttributeError` instead of failing the check.
- [ ] **The boundary.** Exactly `value` words passes (`<=`, not `<`).
- [ ] **Untouched behavior.** Unknown types still raise `ValueError`, and the new branch sits
  inside the JSON group so it doesn't accidentally fall through to `json_field_in`'s
  `value in check["values"]` line.
- [ ] **Docs and tests.** The docstring lists the new type, and the assistant's tests cover the
  edges above, not just the happy path.

## Check it

From the `labs` folder:

```bash
pytest studio-1/03-prompt-test-harness/test_change.py -q
pytest studio-1/03-prompt-test-harness -q
```

The first command runs the acceptance tests for this change. The second runs the whole lab, to
make sure nothing else broke. (`change_solution.py` has a reference version if you want to
compare after you've reviewed your own.)

Stretch (needs an API key): copy `cases.json` to `my_cases.json`, add
`{"type": "json_field_max_words", "field": "summary", "value": 25}` to each case's checks, and run
`python work.py --versions v1 v2 --cases my_cases.json`. Does either version ever exceed the limit?
(Editing a copy keeps the lab's own tests, which read `cases.json`, unchanged.)
