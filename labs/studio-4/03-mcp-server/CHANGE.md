# Change: filter `list_issues` by label

## The change

The most common question a PM asks this server is "which launch blockers are still open?" Today the model can only answer it the long way: list every open issue, then call `get_issue` on each one to read its labels, because summaries do not include labels. That is several tool calls and a lot of context for a one-line answer.

Add an optional `label` filter to `list_issues`, so `list_issues(tracker, status="open", label="launch-blocker")` returns just `HAR-107`. Concretely:

- A new validator, `validate_label`, in the same style as the others: strip and lowercase the value, accept only lowercase letters, digits, and hyphens (1 to 40 characters), and raise `TrackerError` with a message that shows the format (`'launch-blocker'`) for anything else, including non-strings.
- `list_issues` gains `label: str | None = None` as its **last** parameter, after `limit`, so existing positional calls keep working. When given, keep only issues whose `labels` list contains it. It combines with `status`, `assignee`, and `limit`.
- The `list_issues` tool in `build_server` gains the same optional parameter with a `Field` description, and its docstring mentions the launch-blocker question as an example.

Summaries stay at five fields. Nothing else changes. You make the change in `work.py`.

## Write your prompt

Write your own prompt for a coding assistant before you open the example. A good prompt for this change:

- Names the file (`work.py`) and the functions to touch (`list_issues`, the `list_issues` tool in `build_server`) plus the new `validate_label`.
- States the exact validation rule and that errors must be `TrackerError` with a message showing the format, like the other validators.
- Says where the new parameter goes and why (last, so positional calls do not break).
- Says what must **not** change: summary fields, the other tools, the write path, and existing results when no label is given.
- Asks for tests: filtering, combining with other filters, normalization, a well-formed but unknown label, malformed labels, and a "no label means unchanged" regression.

## Example prompt

<details><summary>Show an example prompt</summary>

```text
In labs/studio-4/03-mcp-server/work.py, add an optional label filter to list_issues.

1. Add validate_label(value) next to the other validators. Like validate_issue_id: if value is not a
   string, raise TrackerError; strip and lowercase it; it must fullmatch [a-z0-9-]{1,40} (add a
   LABEL_RE constant next to ISSUE_ID_RE). Every error message must include the example
   'launch-blocker'. Return the normalized label.
2. In list_issues, add label: str | None = None as the LAST parameter (after limit) so existing
   positional calls still work. Validate it only when it is not None, before the loop, and skip
   issues whose labels list does not contain it. Update the docstring.
3. In build_server, add the same optional label parameter to list_issues_tool using
   Annotated[str | None, Field(description=...)] = None, pass it through run(...), and mention
   "which launch blockers are still open?" in the tool docstring.

Do not change issue_summary (summaries keep exactly five fields), the other tools, resources,
the prompt, or anything in the write path. With no label, results must be identical to today.

Add tests for: label alone (launch-blocker gives HAR-101, HAR-104, HAR-107), label with status and
with assignee and limit, a label with spaces and capitals being normalized, an unknown but
well-formed label returning [], malformed labels ("", "launch blocker", "launch_blocker", 41
characters, 7, a list) raising TrackerError, and the old positional call
list_issues(tracker, None, None, 2) still working.
```

</details>

## Review the AI's change

Read the diff before you run anything.

- [ ] **Scope.** Only `validate_label` (and its constant), `list_issues`, and the `list_issues` tool changed. No edits to `issue_summary`, `search_issues`, `get_issue`, the write tool, resources, or the prompt.
- [ ] **Parameter order.** `label` is the last parameter of `list_issues`, after `limit`. If it was inserted before `limit`, `list_issues(tracker, None, None, 2)` now passes 2 as the label.
- [ ] **Validation style.** `validate_label` checks the type before calling `.strip()`, uses `fullmatch` (not `match` or `search`), raises `TrackerError` (not a plain `ValueError` or a silent `None`), and its messages show the format. Its result is the value actually used in the loop.
- [ ] **Matching.** The filter checks membership in the `labels` list (`label in issue.get("labels", [])`), not a substring of something else, and handles issues with no `labels` key.
- [ ] **MCP layer.** The tool's new parameter has a `Field` description, is optional with default `None`, and is passed through `run(...)`. The docstring tells the model when to use it.
- [ ] **No accidental behavior change.** With no label, results are the same as before, and the summaries still have exactly five fields.

## Check it

From the `labs` folder:

```bash
pytest studio-4/03-mcp-server/test_change.py -q
```

Then run the full lab tests to make sure nothing else broke:

```bash
pytest studio-4/03-mcp-server -q
```

If you have SDK 2.x installed, also open the server in the MCP Inspector and look at the `list_issues` input schema: the new `label` parameter and its description should be there.
