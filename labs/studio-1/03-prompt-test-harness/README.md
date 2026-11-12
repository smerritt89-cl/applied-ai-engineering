# Lab 03: A prompt test harness

**Goal:** stop judging prompts by eye. You will build a small harness that runs
two versions of a prompt over the same test set, applies programmatic checks
to every output, and prints a pass-rate table, so a prompt change becomes a
measured change.

This lab goes with lesson `s1-w2-l6`, "Iterating on prompts like an engineer."

## The task

Ledgerly is a fictional invoicing app. Its support team wants each incoming
ticket labeled with a `category` (billing, bug, account, feature_request,
other), an `urgency` (high or low), and a one-sentence `summary`, returned as
JSON so code can route it.

`cases.json` holds ten fictional tickets, each with checks that a correct
answer must pass. Two cases try to hijack the prompt (`injection-approve` and
`tag-breakout`), and two are deliberately awkward (`spam-folder` is ambiguous,
so it accepts two labels; `spanish-download` is not in English).

`starter.py` has two prompt versions:

- **v1** is the kind of prompt most people write first: one vague sentence and
  the ticket.
- **v2** applies week 2's fundamentals: a role and the reason labels matter in
  the system prompt, the ticket first inside escaped `<ticket>` tags,
  category definitions, the instruction last, an explicit rule for urgency, and
  an exact output format.

## Steps

1. Implement the functions marked `TODO` in `starter.py`, in this order:
   `load_cases`, `escape_for_xml`, `render_prompt`, `run_check`, `call_model`,
   `run_suite`, `pass_rate`, `format_table`. The docstrings are the spec.
2. Run the offline tests until they pass (no API key needed):

   ```bash
   cd labs && source .venv/bin/activate
   pytest studio-1/03-prompt-test-harness -q
   ```

3. With `ANTHROPIC_API_KEY` in `labs/.env`, compare the two versions on real
   output:

   ```bash
   cd studio-1/03-prompt-test-harness
   python starter.py --versions v1 v2 --model claude-haiku-5-5
   ```

   Then run it once more on the default model (`claude-opus-5-5`) and compare.
4. Read every failure the script prints. For each one, write one line in a
   notes file: what the output was, and whether the prompt, the check, or the
   test case is wrong.
5. Stretch: add a `v3` that changes exactly one thing from `v2`, and keep it
   only if it beats `v2` without breaking a case `v2` passed.

## Expected cost

Offline tests are free. The single live test makes two calls on
`claude-haiku-5-5`, well under one cent. A full comparison run is 20 calls
(10 cases times 2 versions); on `claude-haiku-5-5` that is well under one
cent, and on `claude-opus-5-5` at low effort it is roughly 10 to 30 cents, depending on how much the model thinks.
Check the pricing page for current rates.

## What to notice

- **v1 fails almost everything, and not because the model is bad.** It was
  never told the output format, so the checks cannot read its answers. Many
  prompt failures are specification failures.
- **Checks are code, so they are cheap and repeatable.** You can rerun the
  whole suite after every change in seconds. Some qualities (is the summary
  faithful?) need a human or a model grader; that comes in Studio 3.
- **Escaping is not a security boundary.** `escape_for_xml` stops the
  `tag-breakout` ticket from closing the tag, which keeps the prompt's
  structure intact. It does not stop a model from obeying instructions written
  inside the data. Watch whether `injection-approve` ever passes on a small
  model, and remember that the real defense is limiting what a model's output
  can do.
- **Results move between models.** Run the same suite on two models and look
  for cases that flip. A prompt tuned on one model is a hypothesis on the next.
- **The same output can vary between runs.** Run the suite twice. If a case
  flips between runs, one run is not evidence; you need repeats (Studio 3
  covers how many).

Stuck? `solution.py` is a working reference. Try for 20 minutes first.
