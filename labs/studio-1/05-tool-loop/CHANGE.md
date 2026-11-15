# Change request: support "in N business days"

You'll make this change in `work.py` (your copy of the solution), using a coding assistant such as Claude Code. Then you review what it did before you accept it.

## The change

People in meetings say "I'll have it to you in three business days" all the time. Today `resolve_date` rejects that phrase, so the model has to leave the due date empty (or, worse, do the math itself).

Add support for `in N business days` (and the singular `in 1 business day`) to `resolve_date`. Business days are Monday to Friday; holidays are out of scope. Count forward from the meeting date, one working day at a time, skipping Saturdays and Sundays. With a Wednesday meeting on `2026-11-11`:

- `in 1 business day` is Thursday, `2026-11-12`
- `in 3 business days` is the following Monday, `2026-11-16`
- `in 5 business days` is the next Wednesday, `2026-11-18`

From a Friday or a Saturday, `in 1 business day` is the next Monday.

The phrase gets the same normalization as the others (case and extra spaces don't matter). The `resolve_date` tool description and the "Cannot resolve" error message must both list the new phrase, because the model only uses phrases the description promises.

Nothing else changes: `in N days` and `in N weeks` keep counting calendar days, and the weekday rules stay exactly as they are.

## Write your prompt

Write your own prompt before you open the example. A good one for this change:

- Names the function, the file, and the exact phrases to accept (singular and plural).
- Defines "business day" precisely (Monday to Friday, no holidays) and gives two or three worked dates, including one that crosses a weekend and one that starts on a weekend.
- Says to update the tool description in `TOOLS` and the error message, not just the code.
- Says what must **not** change: calendar-day phrases, weekday phrases, and the normalization step.
- Asks for tests, and says which cases they should cover.

## Example prompt

<details>
<summary>Show the example prompt</summary>

```text
In work.py, extend resolve_date to accept "in N business days" and
"in 1 business day". Business days are Monday to Friday; ignore holidays.
Count forward from the meeting date one business day at a time, skipping
Saturday and Sunday. Examples with meeting_date 2026-11-11 (a Wednesday):
"in 1 business day" -> 2026-11-12, "in 3 business days" -> 2026-11-16,
"in 5 business days" -> 2026-11-18. From a Friday or Saturday,
"in 1 business day" is the next Monday.

Use the existing normalized phrase p, and re.fullmatch like the other cases.
Do not change how "in N days", "in N weeks", or the weekday phrases resolve.

Update the resolve_date description in TOOLS and the "Cannot resolve" error
message so both list 'in N business days'. Don't touch any other tool,
run_tool, or run_tool_loop.

Add tests for: the three examples above, a Friday and a Saturday start,
mixed case and extra spaces, and a check that "in 3 days" is still
2026-11-14. Then run: pytest studio-1/05-tool-loop -q
```

</details>

## Review the AI's change

Before you accept the change, check:

- [ ] **Scope.** The diff touches `resolve_date`, its entry in `TOOLS`, and the error message. Nothing in `run_tool`, `run_tool_loop`, or the other tools.
- [ ] **Order of the checks.** The business-day pattern must not be swallowed by the calendar-day one. `re.fullmatch` on `in (\d+) (day|days|week|weeks)` won't match "in 3 business days", but if the assistant switched to `re.search` or loosened that pattern, it could. Check that "in 3 days" still gives `2026-11-14`.
- [ ] **Weekends handled both ways.** Counting crosses weekends correctly, and a start on Saturday or Sunday doesn't count the weekend day itself as a business day.
- [ ] **The description promises it.** The `resolve_date` description in `TOOLS` lists the new phrase. If it doesn't, the model will rarely use it.
- [ ] **No scope creep.** No holiday calendar, no new dependency (such as a date library), and no "end of week" or other phrases nobody asked for.
- [ ] **Tests.** New tests cover a weekend crossing and a weekend start, not only the easy Thursday case.

## Check it

From the `labs` folder:

```bash
pytest studio-1/05-tool-loop/test_change.py -q
```

All the change tests should pass. Then run the whole lab to make sure nothing else broke:

```bash
pytest studio-1/05-tool-loop -q
```

`change_solution.py` in this folder is a reference version with the change applied, if you want to compare.
