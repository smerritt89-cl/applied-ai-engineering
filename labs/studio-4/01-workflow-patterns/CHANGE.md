# Change: flag unowned action items in team updates

## The change

The sample notes contain "Someone should update the release checklist before the launch." A good extraction leaves its `owner` null, and today that action quietly disappears into the team update, or is not mentioned at all. Nobody claims it.

Make the team update surface these items:

- Add a constant `NEEDS_OWNER_HEADING = "Needs an owner"`.
- When drafting for the **team** audience and some action facts have no owner, `draft_update` tells the drafter to list those items (by their `text`, one `- ` bullet each) under that heading.
- `code_checks` gets a new deterministic check for the **team** audience: if there are N unowned action facts and the draft does not contain the heading (case-insensitive), add the problem `"unowned actions not flagged: N"`. Because it is a code-check problem, `refine` will feed it back to the drafter and skip the paid model review for that round, with no change to `refine` itself.
- Exec and client updates are unchanged.

You make this change in `work.py` (your copy of the solution), using a coding assistant.

## Write your prompt

Write your own prompt before you open the example. A good prompt for this change:

- Names the file (`work.py`) and the exact functions to change (`draft_update`, `code_checks`), and says `refine` and everything else should not change.
- Gives the exact heading text and the exact problem string, since tests will compare them character for character.
- Says which audience gets the new behavior (team only) and what "unowned" means (an action fact whose owner is null or empty).
- Says the heading check is case-insensitive and that the count is the number of unowned actions the team would see.
- Asks for docstrings to be updated, and for tests: the check fires without the heading, passes with it, ignores exec and client, and the team prompt lists only the unowned actions.

## Example prompt

<details>
<summary>Show the example prompt</summary>

```text
In labs/studio-4/01-workflow-patterns/work.py, make team status updates flag action items that have no owner.

1. Add a module constant NEEDS_OWNER_HEADING = "Needs an owner" next to FALLBACK_AUDIENCE.
2. Add a small helper unowned_actions(facts) that returns the facts with kind "action" and no owner (None or empty), in order.
3. In draft_update, only when audience == "team" and there are unowned actions, append to the prompt an instruction to list them under a heading "Needs an owner", one "- <text>" bullet per item. Do not include owned actions in that list. Other audiences get exactly the prompt they get today.
4. In code_checks, only for audience "team": if facts_for(audience, facts) contains N unowned actions and the draft does not contain NEEDS_OWNER_HEADING (case-insensitive), append the problem "unowned actions not flagged: N". Append it after the existing checks. Keep every existing check and message exactly as it is, including the early return for an empty draft.
5. Update both docstrings to describe the new behavior.

Do not change refine, model_review, status_update, the prompts, the schemas, or the models. Do not add any new model calls.

Add tests (using the existing FakeClient pattern, offline only) for: the problem appears for a team draft without the heading; it does not appear with the heading in any letter case; exec and client drafts never get it; the team draft prompt lists only the unowned actions; and refine sends the problem back to the drafter without calling the reviewer in that round. Then run the existing tests to confirm they still pass.
```

</details>

## Review the AI's change

- [ ] Scope: only `draft_update`, `code_checks`, a constant, and (optionally) a helper changed. `refine`, `model_review`, `status_update`, prompts, schemas, and model names are untouched.
- [ ] The heading text and the problem string match exactly (`Needs an owner`, `unowned actions not flagged: N`), and N counts the unowned actions, not all actions.
- [ ] Team only: exec and client prompts and checks behave exactly as before. A client draft must not suddenly list internal tasks.
- [ ] The heading check is case-insensitive, and the empty-draft early return still comes first.
- [ ] Owned actions are not listed under the heading, and "unowned" covers both `None` and an empty string.
- [ ] No new model call was added (for example, a second model asked to "find unowned items"). This is a deterministic check and should stay in code.
- [ ] Docstrings describe the new behavior, and new tests exist for each case.

## Check it

From the `labs` folder:

```bash
pytest studio-4/01-workflow-patterns/test_change.py -q
```

These tests fail until the change is in `work.py`, and pass once it is right. Then run the full lab tests to make sure nothing else broke:

```bash
pytest studio-4/01-workflow-patterns -q
```

The reference version is `change_solution.py`. Compare it with your assistant's version only after you have reviewed it yourself.
