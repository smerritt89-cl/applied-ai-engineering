# Change: stop a run whose tools keep failing

## The change

The loop already stops on too many model calls, too many tool calls, too many tokens, and
repeated identical calls. It does not stop a model that keeps making *different* bad calls: a
new wrong doc id every step, or arguments that never match the schema. Each of those costs a
model call, and the repeat detector never fires because no two calls are the same. In the trace
this shows up as a long run of `tool_call` events with `is_error: true`.

Add a fourth budget, on failed tool calls:

- `Budget` gets a new field `max_tool_errors` with a default of 5.
- A **tool error** is a call that `run_tool` reports as an error (unknown doc id, bad
  arguments, no search hits, unknown tool). The "Tool call budget exhausted" result is the
  harness's own limit, not a failing tool, so it does **not** count.
- Once the count reaches `max_tool_errors`, the run stops with status `"budget:tool_errors"`,
  after the current batch's results message has been appended (every `tool_use` still gets its
  `tool_result`), and returns the latest text as a partial answer, like the other budgets.
- `AgentResult` gets a `tool_errors` count, and the `stop` trace event records `tool_errors`.

You make the change in `work.py` (your copy of `solution.py`), not in `solution.py` or `starter.py`.

## Write your prompt

Write your own prompt for a coding assistant before you open the example. A good prompt here:

- Names the file (`work.py`) and the pieces to change: `Budget`, `AgentResult`, `run_agent`.
- Defines exactly what counts as a tool error, including the one case that does not.
- Says where the check goes relative to appending the results message, and why (no unpaired
  `tool_use`), and that the stop must go through `finish` so a `stop` event is written.
- Says what must not change: the other budgets, the nudges, the repeat detection, the order of
  results and notes, and the existing tests.
- Asks for tests that use the fake client from the existing test file, with no network.

## Example prompt

<details><summary>Show an example prompt</summary>

```text
In labs/studio-4/02-research-agent/work.py, add a budget on failed tool calls.

1. Add a field to the Budget dataclass: max_tool_errors: int = 5, with a short comment.
2. Add tool_errors: int = 0 as the LAST field of AgentResult (after messages), and add
   "budget:tool_errors" to the status comment.
3. In run_agent, count a tool error each time run_tool returns is_error=True. Do NOT count
   the "Tool call budget exhausted" result; that is the harness's own limit.
4. After the user message with the tool results has been appended and after the existing
   no_progress check, if the count has reached budget.max_tool_errors, return
   finish("budget:tool_errors", last_text). Every tool_use must still have its tool_result.
5. Have finish() pass tool_errors into AgentResult and add tool_errors=... to the "stop" trace event.

Do not change anything else: the other budgets and their order, the wrap-up and repeat nudges,
the order of blocks in the results message, the tools, trimming, or the request sent to the
model. Do not edit the existing tests.

Add offline tests (a scripted fake client like the one in test_research_agent.py, no network)
for: the default of 5; a model that requests a different bad doc id every step stops after
exactly max_tool_errors calls with the right status, count, partial answer, and stop event;
two failing calls in one batch both count and both get results; successful calls do not count;
and the tool-call-budget result does not count. Then run the full lab tests.
```

</details>

## Review the AI's change

- [ ] **Scope:** only `Budget`, `AgentResult`, and `run_agent` changed. No edits to tools, trimming,
      the system prompt, or the request parameters.
- [ ] **What counts:** the counter goes up only on `run_tool` errors, inside the branch that
      actually ran the tool, not on the "Tool call budget exhausted" result.
- [ ] **Placement:** the check runs after `messages.append({"role": "user", "content": results})`,
      so the history stays valid, and it returns through `finish` so a `stop` event is written.
- [ ] **Compatibility:** `tool_errors` was added at the end of `AgentResult` with a default, so
      existing positional construction still works; the existing tests still pass.
- [ ] **Defaults:** `Budget()` with no arguments behaves as before for any run with fewer than 5 tool
      errors (check that nothing else shifted, such as the order of the existing budget checks).
- [ ] **Docs:** the `AgentResult.status` comment lists the new status. Bonus: the README's list of
      stop reasons in "What to notice" mentions it too.

## Check it

From the `labs` folder:

```bash
pytest studio-4/02-research-agent/test_change.py -q   # passes only when the change is right
pytest studio-4/02-research-agent -q                  # the original tests must still pass
```
