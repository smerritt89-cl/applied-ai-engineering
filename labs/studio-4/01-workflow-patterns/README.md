# Lab 01: Workflow patterns for a status update

**Goes with:** Studio 4, week 1 (lessons 1 to 3). **Time:** about 75 minutes.

## Goal

Turn raw meeting notes into a status update for the right audience, using three workflow patterns from
Anthropic's "Building effective agents". Your code chooses every step, so this is a workflow, not an agent:

1. **Routing.** A cheap model (`claude-haiku-5-5`) classifies the request as `exec`, `team`, or `client`. A strict
   parser accepts only those labels; anything else falls back to `team`, which is internal, so a confused router
   never sends internal detail outside.
2. **Prompt chaining with a gate.** Call 1 extracts decisions, action items, risks, and updates as JSON (structured
   outputs), each with a verbatim quote. A **gate in plain code** rejects items whose quote or owner is not in the
   notes. Call 2 drafts the update from the verified facts only.
3. **Evaluator-optimizer.** Deterministic checks run first (word limit per audience, every action owner named, no
   confidential terms in a client update). Only if they pass does a different model (`claude-sonnet-5-5`) review the
   draft against a rubric. Problems go back to the drafter. After `max_rounds`, the last draft is returned with
   `approved=False`, for a person to decide.

The sample in `samples/weekly-sync.md` is fictional. It contains an internal codename, a confidential margin note,
an action with no owner, and a risk that must not reach the client.

## Steps

Work in `starter.py`. The tests import from it. The prompts, schemas, and the helpers `normalize`, `facts_for`,
`extract_facts`, `draft_update`, and `model_review` are given; read them first, since your functions call them.

1. **One call.** Write `text_of` (check `stop_reason`, skip thinking blocks) and `call` (one user message,
   `output_config` with the effort and an optional `format`, no sampling parameters).
2. **Routing.** Write `parse_audience` and `route_audience`.
3. **The gate.** Write `gate_facts`. Normalize whitespace; check empty quote, then quote in notes, then owner in notes.
4. **Checks and the loop.** Write `code_checks`, then `refine`. Skip the model review when code checks already failed:
   there is no point paying for a review of a draft you know is wrong.
5. **The workflow.** Write `status_update`. Raise `GateFailed` before any drafting if the gate keeps nothing.
6. Run the offline tests until they pass:

   ```bash
   cd labs && source .venv/bin/activate
   pytest studio-4/01-workflow-patterns -q
   ```

7. With a key in `labs/.env`, run the live test and the script:

   ```bash
   pytest studio-4/01-workflow-patterns -q -m live -s
   python studio-4/01-workflow-patterns/starter.py
   ```

## How the fake client works

`FakeClient` in the tests records every `messages.create(**kwargs)` call and returns scripted replies in order. That
lets the tests check things a live run can't show reliably: that the router uses the cheap model at low effort, that
the gate stops the pipeline before any draft is written, that a draft failing code checks never pays for a model
review, and that the next draft's prompt contains the specific problems. It raises if your code makes an unexpected
extra call, which catches loops that don't stop.

This is the same technique you will use for agents in week 2: test the control logic with scripted model replies,
then test model quality separately with evals.

## Expected cost

Offline tests: free. The live test runs the whole pipeline once: one Haiku 5.5 call, one Opus 5.5 extraction, one to
three Opus 5.5 drafts, and up to three Sonnet 5.5 reviews, on a few hundred words of notes. At the list prices on the
review date (per million input and output tokens: Opus 5.5 $4 and $20, Sonnet 5.5 $2 and $10, Haiku 5.5 $0.10 and
$0.50) that is well under ten cents. Check the current pricing page before relying on those numbers.

## What to notice

- **The gate catches what the schema can't.** Structured outputs guarantee the JSON shape. Only your gate knows
  whether a quote is real. Run the live test with `-s` and look at what was rejected and why.
- **"Someone should update the release checklist."** A good extraction leaves `owner` null. If the model invents an
  owner, the gate rejects the item only when that name isn't in the notes; a plausible attendee's name would pass.
  That is a judgment a person should see. Consider adding a check that lists unowned action items in the team update so someone claims them.
- **Routing is model selection.** The router costs a fraction of a cent. Try sending the router's job to Opus 5.5
  and compare cost and accuracy on ten requests you label yourself. Measure before deciding the cheap model is
  good enough.
- **The evaluator is a separate model with a rubric, and it is still not ground truth.** Before trusting the loop
  in a real project, feed `model_review` drafts you know are bad and confirm it rejects them (Studio 3, week 2).
- **Refusal fallbacks.** Anthropic offers a beta server-side fallback that re-runs a declined request on another
  model. It is left out here to keep the calls simple; `text_of` raises `StepFailed` on a refusal instead.
