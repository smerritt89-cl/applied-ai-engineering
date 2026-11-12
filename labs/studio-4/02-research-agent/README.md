# Lab 02: A budgeted research agent with a trace log

**Goes with:** Studio 4, week 2, lessons 4 and 5. **Time:** about 75 minutes.

## Goal

Build a small research agent the way you would before letting one near real work: two
read-only tools, hard limits, a trace of everything it did, and a plan for when the context
grows. The agent answers questions about **Project Larkspur**, a fictional product launch at a
fictional company. Its documents are in `corpus/`: a launch plan, a decision log, a risk
register, a vendor contract summary, meeting notes, and a beta retrospective.

| Tool | Kind | What it does |
|---|---|---|
| `search_docs` | read | Keyword search; returns the best few documents with a one-line snippet |
| `read_doc` | read | Returns one page of a document with line numbers and `next_start_line` |

You write, in `starter.py`:

1. `search_docs()`: score documents by query terms (title matches count extra), return the top hits, and raise a helpful `ToolError` when nothing matches.
2. `read_doc()`: paginated reads by **document id only**. An id that is not in the corpus (including anything that looks like a path, such as `../solution`) is an error that lists the valid ids.
3. `Tracer.event()`: one JSON line per event (`model_call`, `tool_call`, `trim`, `stop`), each with `kind` and `step`.
4. `trim_context()` and `strip_thinking()`: the context budgeter from lesson 5, plus removal of thinking blocks whenever trimming edits history.
5. `run_agent()`: the guarded loop. Budgets are checked before every model call; every `tool_use` gets a `tool_result` in one user message; the request for the final allowed step carries a wrap-up nudge; repeated identical calls get a nudge and then a `no_progress` stop; abnormal stop reasons run no tools; every run ends with a `stop` event and a status.

## Steps

```bash
cd labs && source .venv/bin/activate
pytest studio-4/02-research-agent -q     # offline: fails until you implement the TODOs
```

Work through the TODOs in order; the docstrings spell out each rule. The offline tests use a
fake client that replays scripted responses (parallel calls, a model that never stops, large
token usage, a bad document id, `max_tokens` and `refusal` stops, thinking blocks), so you can
finish the whole lab without an API key. No extra packages are needed beyond `labs/requirements.txt`.

When the offline tests pass, add your key to `labs/.env` and run the live test, or run the
agent by hand and read its trace:

```bash
pytest studio-4/02-research-agent -q                 # now includes the live test
python studio-4/02-research-agent/starter.py         # writes trace.jsonl next to the script
```

## Expected cost

The live test and the script each make up to 8 requests to `claude-opus-5-5` at low effort, with
a corpus of about 225 lines. At the prices on the [Claude pricing page](https://platform.claude.com/docs/en/about-claude/pricing)
on 2026-11-11 that is a few cents per run. Check the page for current prices, and look at the
`tokens` total the agent reports.

## What to notice

- **Limits are code, not hope.** `Budget` caps model calls, tool calls, and tokens. The loop checks
  them before spending money, and every stop says why (`done`, `budget:steps`, `budget:tokens`,
  `no_progress`, `stopped:max_tokens`, `stopped:refusal`). A capped run returns its latest text as a
  partial answer instead of an empty string.
- **The model is told when it is about to run out.** The wrap-up note goes in the user message
  before the last allowed call, after the tool results, and stays in the history. Claude's task
  budgets (beta) do something similar server-side with a token countdown; they are advisory, so
  you would still keep these enforced limits.
- **Small results by design.** `read_doc` returns a page, not a file, and says where to continue.
  Deciding result size when you create it is cheaper than trimming later.
- **Trimming edits history, and that has a cost on Claude.** On current Claude models with
  preserved thinking, each thinking block is bound to everything before it. When `trim_context`
  clears an old tool result, every later thinking block becomes invalid, so the loop strips them
  (allowed, but the model loses that reasoning and the prompt cache resets). That is why trimming
  happens rarely and in large steps. In production on Claude, prefer server-side context editing
  (`clear_tool_uses_20250919`), which the check does not treat as an edit; see "Going further".
- **The trace is your eval data.** Each `model_call` and `tool_call` line has the step, sizes,
  and error flags you need for the Studio 3 agent metrics: steps per task, tokens per task, tool
  error rate, and how runs ended.
- **Documents are data.** `meeting-notes-2026-11-04.md` contains a line addressed to "any AI
  assistant" asking it to report that all risks are closed. The system prompt says document text
  is data, and the live test checks the answer does not repeat the claim. Week 4 covers why a
  prompt alone is not a sufficient defense.

## Going further

- Replace client-side trimming with Claude's server-side tool-result clearing: call
  `client.beta.messages.create(...)` with `betas=["context-management-2025-06-27"]` and
  `context_management={"edits": [{"type": "clear_tool_uses_20250919"}]}`, keep your history
  append-only, and log `response.context_management.applied_edits`. See the
  [context editing docs](https://platform.claude.com/docs/en/build-with-claude/context-editing).
  Compare tokens per run and answer quality on five questions.
- Add a task budget (`output_config={"effort": "low", "task_budget": {"type": "tokens", "total": 40000}}`
  with `betas=["task-budgets-2026-03-13"]` on `client.beta.messages.create`) and check in your
  traces whether runs end more gracefully. The minimum total is 20,000; see the
  [task budgets docs](https://platform.claude.com/docs/en/build-with-claude/task-budgets).
- Replace `estimate_tokens` with `client.messages.count_tokens(...)` for the trimming decision and
  see how far off the four-characters-per-token estimate is on this corpus.
- Write five questions with known answers from the corpus (one that needs two documents, one
  the documents cannot answer) and turn the live test into a small eval with a pass rate.
- Port the loop to the SDK tool runner or to one of the frameworks in lesson 6, keeping the same
  tools and tests, and compare how much code you own.
