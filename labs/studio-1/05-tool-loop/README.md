# Lab 05: The tool-use loop, with a gated write tool

**Goes with:** Week 4, lessons 10 and 11. **Time:** about 60 minutes.

## Goal

Write the manual tool-use loop yourself, with the official `anthropic` SDK, for a
small slice of the Studio 1 project: turning a line from meeting notes into a task
with a real owner and a real date. You get three tools:

| Tool | Kind | What it does |
|---|---|---|
| `lookup_teammate` | read | Finds a person in `team.json` by name or alias |
| `resolve_date` | read | Turns "next Friday" into an ISO date, measured from the meeting date |
| `create_task` | **write** | Appends a task to a local `tasks.json`; needs human approval |

The tool definitions (`TOOLS`) and two of the implementations are done. You write:

1. `resolve_date()`: the date rules that the tool description promises.
2. `run_tool()`: the dispatcher. Read tools run directly. The write tool is validated
   first, then sent to an `approve` callback, and runs only on a yes.
3. `run_tool_loop()`: call the model, run every requested tool, send all results back
   in one user message, repeat until `stop_reason` is `end_turn`, and never exceed
   `max_iterations` model calls.

## Steps

```bash
cd labs && source .venv/bin/activate
pytest studio-1/05-tool-loop -q          # offline: should fail until you implement the TODOs
```

Work through the TODOs in `starter.py` in order. The offline tests use a fake client that
replays scripted responses (including two parallel `tool_use` blocks, an error, a write
the user declines, a model that never stops, and a truncated turn), so you can finish
the whole lab without an API key.

When the offline tests pass, add your key to `labs/.env` and run the live tests, or try it
by hand:

```bash
pytest studio-1/05-tool-loop -q          # now includes the two live tests
python studio-1/05-tool-loop/starter.py  # prompts you to approve each create_task
```

## Expected cost

The two live tests make roughly 3 to 8 requests to `claude-opus-5-5` at low effort, with
small inputs. At the prices listed on the [Claude pricing page](https://platform.claude.com/docs/en/about-claude/pricing)
on 2026-11-11 that is a few cents in total. Check the page for current prices.

## What to notice

- **The model never runs anything.** It returns `tool_use` blocks; your code decides what
  runs. That is where every check in this lab lives.
- **One user message per turn of results.** When the model asks for two tools at once, both
  `tool_result` blocks go back together. Splitting them across messages is the most common
  reason models stop making parallel calls (see the parallel tool use docs).
- **Errors are data.** A bad phrase or an unknown person comes back as a `tool_result` with
  `is_error: true` and a message that says what to try instead. The loop keeps going.
- **Validate, then ask, then act.** `strict: true` guarantees the arguments match the schema,
  but not that the email belongs to a teammate. Your own check runs before a human is asked,
  so nobody approves nonsense.
- **Deny by default.** `deny_all` is the default approver. A write happens only when you pass
  an approver that says yes.
- **The loop is bounded.** `max_iterations` caps cost and stops a model that keeps calling
  tools. Any stop reason other than `tool_use`, `end_turn`, or `pause_turn` (for example
  `max_tokens`, which can cut a tool call off mid-input, or `refusal`) ends the loop without
  running tools.
- **No forced tool choice.** On `claude-opus-5-5`, `tool_choice` of `any` or `tool` is
  rejected, so the system prompt names the tools to use instead.

## Going further

- Rewrite the loop with the SDK's tool runner (`client.beta.messages.tool_runner` with
  `@beta_tool` functions) and gate `create_task` inside the tool function. Compare how much
  code you own. See the [tool runner docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner).
- Production code on current Claude models should also handle `refusal` with a fallback model;
  see [Refusals and fallback](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback).
  This lab simply stops.
- Log `result.tool_calls` to a JSONL file. You will want exactly this record when you build
  evals in Studio 3.
