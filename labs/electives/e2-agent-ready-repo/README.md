# Lab: an agent-ready repo, measured

**Goes with:** Elective 2, Working with Coding Agents (all three weeks; the comparison exercise is the core of
lessons e2-w1-l3, e2-w2-l5, and e2-w3-l7). **Time:** 60 to 120 minutes, most of it watching agents work.
**Cost:** each agent run on this tiny repo typically costs well under a dollar on API pricing, or a small slice
of a subscription's usage; six to nine runs in total. Check your own numbers with `/usage` or the
`total_cost_usd` field described below.

## What's here

| Path | What it is |
|---|---|
| `starter.py` | The sample repo's application code: order pricing with integer cents, bulk tiers, promo codes, tax. It has seeded bugs. |
| `test_pricing.py` | The sample repo's test suite. Four tests fail against `starter.py`. |
| `solution.py` | One small, correct fix. Never shown to the agent. |
| `holdout/holdout_pricing.py` | Hidden tests that check whether a fix generalizes. Never shown to the agent. |
| `setups/memory/` | Project memory only: a short `CLAUDE.md`. |
| `setups/full/` | `CLAUDE.md` plus `.claude/settings.json` (hooks and deny rules), two hook scripts, and a read-only `reviewer` subagent. |
| `templates/CLAUDE.md.template` | A starter template for your own repos (project requirement 2). |
| `make_workspace.py` | Builds a clean workspace for each run and scores it afterwards. |
| `test_lab_setup.py` | Offline checks that the hooks config has the documented shape and that the hook scripts behave. |

## Step 0: offline checks

```bash
cd labs && source .venv/bin/activate
pytest electives/e2-agent-ready-repo -q
```

Expect **4 failed, 24 passed**. The four failures are the sample repo's tests against the buggy `starter.py`;
that's the task. All of `test_lab_setup.py` should pass. If you edit anything under `setups/`, rerun this.

To see what a good fix looks like, compare the two versions: `diff starter.py solution.py`. Three focused
edits, no test changes, no new dependencies, every safeguard kept. Hold agents to that standard.

## Step 1: understand the setups before you use them

Read `setups/full/.claude/settings.json` next to the hooks guide (https://code.claude.com/docs/en/hooks-guide).
Then answer, in your notes:

1. The `PostToolUse` hook exits with code 2 when tests fail. What does that do on `PostToolUse`, given the edit
   already happened? What does the same exit code do on `Stop`?
2. `protect_tests.py` blocks `Edit` and `Write` calls on `tests/`. Name two ways an agent could still change a
   test file. Which line in `settings.json` covers one of them, and what covers the other?
3. Why does `run_tests.py` exit 0 when `stop_hook_active` is true?

(Answers: lesson e2-w2-l5 covers 1 and 3; lesson e2-w3-l7 covers 2.)

## Step 2: run the same task under three setups

Create one workspace per run, **outside this repository** (the agent should see only the workspace). Keep your
virtual environment active so `python3 -m pytest` works inside the workspace and inside the hooks.

```bash
python electives/e2-agent-ready-repo/make_workspace.py create ~/agent-runs/bare-1   --setup bare
python electives/e2-agent-ready-repo/make_workspace.py create ~/agent-runs/memory-1 --setup memory
python electives/e2-agent-ready-repo/make_workspace.py create ~/agent-runs/full-1   --setup full
```

Each workspace is its own git repo with one commit, so `git diff` shows exactly what the agent changed.

In each workspace, start a **fresh** session and give the same prompt, word for word:

```text
Fix ticket #142 in README.md.
```

Keep everything else the same across runs: model, effort level, permission mode. The short prompt is
deliberate: you're measuring what the repo setup contributes, not your prompting. (A second round with a
detailed prompt is a good stretch exercise.)

For an unattended, comparable run, use non-interactive mode. This example caps turns and spend and records
the cost estimate:

```bash
cd ~/agent-runs/full-1
claude -p "Fix ticket #142 in README.md." --permission-mode acceptEdits \
  --allowedTools "Bash(python3 -m pytest *),Bash(git diff *)" \
  --max-turns 30 --max-budget-usd 2 --output-format json > run.json
```

Don't add `--bare` here: bare mode skips `CLAUDE.md` and hooks, which is the whole point of the comparison.
Note what that implies about other people's repos: a `claude -p` run executes a project's hooks without a
trust dialog. Only run this in workspaces you created.

`run.json` includes `total_cost_usd` (a client-side estimate) and the final `result` text. In an interactive
session, run `/usage` at the end instead.

## Step 3: score each run

```bash
python electives/e2-agent-ready-repo/make_workspace.py score ~/agent-runs/full-1
```

This reports the visible tests, the **holdout** tests (other tier boundaries, other promo codes, the expiry
rule, exact rounding on a very large order), whether `tests/test_pricing.py` was modified, and which files
changed. Then read the diff yourself (`git diff` in the workspace) with the lesson e2-w3-l8 checklist.

Record one row per run in a copy of this table:

| Run | Setup | Visible tests pass | Holdout pass (of 8) | Tests edited? | Safeguards kept? | Files changed | Your rework (min) | Wall time (min) | Cost |
|---|---|---|---|---|---|---|---|---|---|
| bare-1 | bare | | | | | | | | |
| memory-1 | memory | | | | | | | | |
| full-1 | full | | | | | | | | |

"Rework" is the time you'd need to get the change mergeable: fixing what the agent missed, reverting what it
shouldn't have touched.

## Step 4: repeat, then decide

One run per setup is an anecdote. Agents vary from run to run, so do at least two more runs of each setup
(`bare-2`, `bare-3`, ...) and compare rates, not single outcomes. Then write three sentences: which setup you'd
use for this kind of task, what it cost, and what surprised you. Typical things to notice:

- Did any run pass the visible tests but fail the holdout (for example, fixing the 10-unit boundary without
  the 50 and 100 boundaries, or rounding with floats)? Passing tests is necessary, not sufficient.
- Did a bare run edit a test, or remove the expiry check while making codes case-insensitive?
- Did the hooks change how many turns the agent took, or what it cost?

## Stretch

1. Swap the model or effort level (for example `/model sonnet` or `/effort high`) with the full setup held
   fixed, and compare cost per successful run.
2. Run the same task in a second agent (Codex, Gemini or Antigravity CLI, Copilot, Cursor). Translate the
   setup: most read `AGENTS.md` (copy `CLAUDE.md` to `AGENTS.md` or import it with `@AGENTS.md`); hooks and
   deny rules are product-specific, so check each tool's docs for its equivalent and note what you couldn't
   reproduce.
3. Write a fourth setup: add a skill at `.claude/skills/fix-ticket/SKILL.md` with your team's bug-fix
   procedure (reproduce with a failing test, fix, run the suite, request review) and measure it.

## What to notice

The bug is small on purpose. The interesting differences are not "did it pass" but how much of your attention
each setup needed: whether the agent ran the tests on its own, whether it reported evidence, whether it
touched things it shouldn't, and whether its fix held up on cases it never saw. That's the measurement the
elective project asks you to make on a repo of your own.
