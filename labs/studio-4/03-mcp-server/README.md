# Lab 03: An MCP server for an issue tracker

**Goes with:** Studio 4, week 3 (lessons 7 to 9). **Time:** about 75 minutes.

## Goal

Build a Model Context Protocol server that gives an AI host (Claude Code, Claude Desktop, or any MCP client)
access to a small fictional issue tracker, the backlog for a customer portal relaunch stored in
`data/issues.json`. The server exposes:

- **Three read tools:** `list_issues`, `search_issues`, `get_issue`.
- **One write tool:** `update_issue_status`, which returns a preview unless it is called with `confirm=true`.
- **Resources:** a fixed `tracker://summary` and a template `tracker://issues/{issue_id}`.
- **A prompt:** `triage_issue`, a user-invoked template for triaging one issue.

The work is split into two layers on purpose. The tracker logic and every input check are plain Python with no
MCP imports, so you can test them offline and reuse them anywhere. The MCP layer (`build_server`) is thin: it
declares tools, resources, and a prompt, and translates validation errors into tool errors the model can read.

## Setup

The offline tests need only the shared lab environment. The MCP layer needs the official Python SDK, version 2
(the version that supports the `2026-07-28` protocol revision and renames `FastMCP` to `MCPServer`):

```bash
cd labs && source .venv/bin/activate
pip install "mcp[cli]"            # SDK 2.x; check the SDK README for the supported Python versions
```

`test_server_sdk.py` is skipped automatically until the SDK is installed. To try the MCP Inspector you also need
Node.js (the Inspector docs list Node 22.19.0 or newer).

## Steps

Work in `starter.py`. The tests import from it.

1. **Validation.** Write `validate_issue_id`, `validate_limit`, and `validate_query`. Every rejection raises
   `TrackerError` with a message that tells the caller how to fix the input. Watch for `True` passing as an `int`.
2. **`clean_text`.** Remove invisible Unicode format characters (category `Cf`) and control characters other than
   newline and tab, then truncate. Look at issue HAR-105 in the data file to see why.
3. **Reads.** Write `list_issues` and `search_issues` (the given `get_issue` shows the pattern).
4. **The write.** Write `plan_status_change` and `update_issue_status`. Only the boolean `True` confirms; a
   repeated call is a no-op; an invalid call raises before anything changes.
5. Run the offline tests until they pass:

   ```bash
   pytest studio-4/03-mcp-server/test_tracker.py -q
   ```

6. **The MCP layer.** In `build_server`, finish TODO 1 to 3: the write tool, the resource template, and the prompt.
   The read tools and the summary resource are written for you as models. Then run all tests:

   ```bash
   pytest studio-4/03-mcp-server -q
   ```

## Inspect it, then connect it

Use a copy of the data so experiments do not change the sample file:

```bash
cp studio-4/03-mcp-server/data/issues.json /tmp/harbor-issues.json
export HARBOR_TRACKER_PATH=/tmp/harbor-issues.json
```

**MCP Inspector (no model in the loop).** This is the first place to look at what your server really exposes:
tool names, descriptions, schemas, annotations, and raw results.

```bash
npx @modelcontextprotocol/inspector python studio-4/03-mcp-server/starter.py
# or, scripted:
npx @modelcontextprotocol/inspector --cli python studio-4/03-mcp-server/starter.py --method tools/list
```

**Claude Code.** Register the server with absolute paths (hosts launch servers from their own working directory):

```bash
claude mcp add harbor --env HARBOR_TRACKER_PATH=/tmp/harbor-issues.json -- \
  /ABSOLUTE/PATH/labs/.venv/bin/python /ABSOLUTE/PATH/labs/studio-4/03-mcp-server/starter.py
```

Run `/mcp` inside Claude Code to check that `harbor` is connected. Then ask: "What is blocking the Harbor
launch?" and "Triage HAR-105." Its tools appear to Claude Code as `mcp__harbor__list_issues` and so on, and that
is also the name you would use in a permission rule.

**Claude Desktop.** Add an entry under `mcpServers` in `claude_desktop_config.json` with the same command and
arguments (see the official "Build an MCP server" tutorial for the file location), then fully quit and reopen
the app. (The SDK's `mcp install` helper looks for a module-level server object named `mcp`, `server`, or `app`.
This lab builds the server inside `build_server()` so tests can point it at a temporary file, so write the
entry by hand.)

## Expected cost

The tests make no model calls and cost nothing. Using the server from Claude Code or Claude Desktop uses your
normal plan or API usage for those conversations.

## What to notice

- **HAR-105 is a prompt injection.** A customer comment contains instructions aimed at the assistant, wrapped in
  zero-width spaces. `clean_text` makes the hidden characters visible as nothing, but the instruction text stays:
  cleaning text is not the same as making it trustworthy. Watch what Claude does when it triages HAR-105, and
  which layer stops a bad write: the tool description, the preview step, or the host's permission prompt.
- **`confirm` is set by the model, not by a person.** The preview-then-confirm protocol forces a round trip and
  gives the host something concrete to show the user, but a model that has been fooled can pass `confirm=true`.
  The real human gate is the host's approval prompt for the write tool (or, in the 2026-07-28 protocol,
  an elicitation request the client shows to the user). Keep Claude Code asking before it runs
  `mcp__harbor__update_issue_status`.
- **Annotations are claims.** `read_only_hint=True` on your read tools is honest because you wrote them. The
  specification tells clients to treat annotations from untrusted servers as untrusted.
- **Two kinds of error.** A bad issue id comes back as a tool result with `is_error` true and a message the model
  can act on. An exception you did not anticipate becomes a generic error, and the details stay in your server's
  log. Try both in the Inspector.
- **stdout is the protocol.** Over stdio, anything your server prints to stdout corrupts the message stream. Log
  with the `logging` module, which writes to stderr.
