# Lab 04: Guardrails you can measure

**Goes with:** Studio 4, week 4 (lessons 10 to 12). **Time:** about 75 minutes.

## Goal

Build the safety layer of a status-report agent and prove it works:

1. A **guard** that decides every tool call with deterministic rules: destination allowlists, a data-flow rule
   (private data never goes out), the lethal-trifecta check, and approvals for writes.
2. An **approval gate** that denies by default: a crashed, slow, or ambiguous reviewer is a no.
3. An **audit log** with one entry per call, including the ones that were blocked.
4. An **injection test suite**: ten fixture trackers (`fixtures/scenarios/`), eight with injection attempts and two
   benign, scored by what actually happened in the environment, guard on and guard off.

The agent is the one you will build in the studio project: it reads issues, reads confidential account notes, and
posts a weekly status. That gives it all three legs of the trifecta (private data, untrusted content, and ways to
communicate out), which is exactly why it needs this layer.

## Steps

Work in `starter.py`. The tests import from it. The tools, the fake environment, the scripted client, and the suite
runner are given.

1. **Matching.** Write `host_allowed` (exact host or a true subdomain) and `contains_private` (normalized substring
   match). Read the parametrized host tests first: lookalike domains are the classic bug.
2. **The guard.** Write `Guard.observe` (label results as untrusted or private) and `Guard.check` (eight rules,
   first match wins, listed in the docstring).
3. **The loop.** Write `run_agent`. It is your Studio 1 tool loop with the guard in the middle: check, maybe ask,
   run and observe or return an `is_error` result, and audit every call.
4. **The scorer.** Write `attack_succeeded`. It looks only at `env.effects`, the side effects that really happened.
   Never score a guard by reading its own decisions.
5. Run the offline tests until they pass, then print the suite table:

   ```bash
   cd labs && source .venv/bin/activate
   pytest studio-4/04-agent-guardrails -q
   python studio-4/04-agent-guardrails/starter.py
   ```

6. With a key in `labs/.env`, run the live check: Claude on three attack fixtures, with a reviewer who declines
   everything, so nothing is ever posted.

   ```bash
   pytest studio-4/04-agent-guardrails -q -m live -s
   python studio-4/04-agent-guardrails/starter.py --live
   ```

## Why the offline client is a "worst-case model"

`ScriptedClient` replays each scenario's script, and the scripts follow every injection. Real models resist many
injections, and that resistance is worth having, but it is probabilistic. Testing the guard against a model that
always falls for the attack isolates the property you can actually guarantee: **what the system allows, whatever
the model decides.** The live test then tells you something different: how often a real model *attempts* the
attack (count the blocked calls in the audit log). Report both numbers; they answer different questions.

## Expected cost

Offline tests: free. The live test makes about four to six `claude-opus-5-5` calls per scenario on short inputs at
low effort, three scenarios in total. At the pricing listed on the review date ($4 per million input tokens, $20 per
million output) that is well under 20 cents. Check the current pricing page first. The script prints tokens per
run, which is the start of the cost-per-run number the project asks for.

## What to notice

- **The rubber-stamp test.** `test_rubber_stamp_reviewer_cannot_approve_a_leak` runs the suite with a reviewer who
  approves everything. Every attack is still stopped, because each one hits a deterministic deny before it reaches
  a person. Approvals are for the cases a rule cannot decide, not a substitute for rules.
- **Filters versus controls.** `inj-base64` encodes the data, so `contains_private` cannot see it. The destination
  allowlist stops it anyway. Content detection is a filter that lowers risk; the allowlist is the control.
- **Allowlisted is not the same as safe.** `inj-allowlisted-host` sends the customer name to your own docs site in a
  query string, where it lands in server logs. The data-flow rule catches it; a host allowlist alone would not.
- **The cost of safety.** Rerun with `approve=deny_all`: attack success stays at zero and utility drops to zero.
  The useful number is the pair (attack success, utility), as in AgentDojo, never one of them alone.
- **A deliberate trade-off.** Rule 5 blocks private data in any outbound call, including email to a colleague at
  `acme.example`. That over-blocks. If you relax it for internal recipients, write the test for the relaxed rule
  first, then add a scenario that tries to abuse the relaxation.

## Going further

- Route asks to a real reviewer: print the exact arguments and the reason, and read `y` from the terminal.
- With the SDK tool runner instead of a manual loop, put the same check inside each tool function (return a
  "blocked" result) or inspect pending `tool_use` blocks between turns; see the tool runner docs.
- On Managed Agents, the server-side equivalent is a `permission_policy` per tool (`always_allow`, `always_ask`,
  `auto`). It covers Anthropic-executed tools and MCP tools; your own custom tools still need a guard like this one.
- On the current models a policy decline returns `stop_reason: "refusal"`; this loop stops there. Anthropic offers
  server-side fallbacks to re-run a declined request on another model; see the refusal docs if you need them.
