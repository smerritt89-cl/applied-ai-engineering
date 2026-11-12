# Lab 01 (Studio 3): Error analysis on a support bot

**Goes with:** Studio 3, week 1 (lessons 1 to 3). **Time:** about 90 minutes, most of it reading traces.

## Goal

Before you write a single grader, find out how your system actually fails. You will:

1. Load 36 traces from a fictional support bot for **Tallyhub**, an invoicing app (`data/traces.jsonl`).
2. Annotate them in a spreadsheet: pass or fail, an open-ended note (**open coding**), then a failure-mode label
   from a small taxonomy (**axial coding**).
3. Validate the annotations in code, count failure modes, rank them, and write a short prioritized report.
4. Optionally, generate synthetic test inputs along defined dimensions with Claude, as a start on next week's test set.

Everything except step 4 runs offline. The data is invented for this lab; Tallyhub is not a real product.

## Files

| File | What it is |
|---|---|
| `data/kb.md` | The help-center excerpt the bot retrieves from. This is your ground truth when judging a trace. |
| `data/traces.jsonl` | 36 traces: user message, retrieved sections, bot response, plus channel and plan. |
| `data/annotations.csv` | A completed annotation by one reviewer, so the tests have fixed numbers. |
| `data/taxonomy.json` | The failure taxonomy that reviewer arrived at, with a definition and a severity (1 to 3) per mode. |
| `starter.py` | Your file. Functions with docstrings and `TODO`s. The tests import from it. |
| `solution.py` | A reference implementation. Try first. |

## Steps

1. **Annotate first, code second.** Generate a blank sheet and do your own pass before you look at
   `data/annotations.csv`:

   ```bash
   cd labs && source .venv/bin/activate
   python -c "import sys; sys.path.insert(0, 'studio-3/01-error-analysis'); import solution as s; \
   s.write_annotation_template(s.load_traces(s.DATA_DIR / 'traces.jsonl'), 'my_annotations.csv')"
   ```

   Open `my_annotations.csv` in a spreadsheet. For each trace, read the user message, the response, and the relevant
   part of `data/kb.md`. Write `pass` or `fail` and, for failures, one sentence in `note` about the **first thing that
   went wrong**. Don't use categories yet. When you've done all 36, read your notes and group them into five to
   eight failure modes; put those labels (semicolon-separated) in `failure_modes`.
2. **Compare with the reference reviewer.** Diff your labels against `data/annotations.csv`. Where you disagree,
   decide who is right using the knowledge base, and note any trace where the knowledge base itself is ambiguous
   (look at t10 and the existing-customer pricing rule). Disagreement is information, not failure.
3. **Implement the toolkit** in `starter.py`, in order: `load_traces`, `load_taxonomy`, `write_annotation_template`,
   `parse_modes`, `load_annotations`, `count_failure_modes`, `uncoded_failures`, `summarize`, `prioritize`,
   `render_report`, `make_tuples`, `generate_queries`. Run the tests until they pass:

   ```bash
   pytest studio-3/01-error-analysis -q
   ```

4. **Produce the report** for the reference annotations (`python studio-3/01-error-analysis/starter.py`, which
   writes `report.md`), then point `main()` at your own CSV and taxonomy and compare the two rankings.
5. **Optional live step.** With a key in `labs/.env`:

   ```bash
   pytest studio-3/01-error-analysis -q -m live -s
   ```

   Then try `generate_queries(anthropic.Anthropic(), make_tuples(DIMENSIONS)[:6])` in a REPL and read the results.

## How the synthetic step works

This follows the two-step approach in Husain and Shankar's evals FAQ: first choose **dimensions** (here topic, plan,
and style) and build structured **tuples**, then turn each tuple into a natural-language message in a separate call.
Generating from tuples gives you coverage you chose on purpose, instead of a hundred variations of the same polite
question. `exclude` lets you drop combinations that make no sense for your product.

The call uses `client.messages.parse(..., output_format=SyntheticQuery)`, the Python SDK's structured outputs helper
(Studio 1, week 3), so each reply is a validated Pydantic object. It sets no sampling parameters, which the current API
rejects. Anthropic also offers a beta server-side fallback for refused requests; it is left out here to keep the call
simple, and `generate_queries` raises on a refusal instead.

## Expected cost

Offline tests: free. The live test makes two short calls to `claude-opus-5-5` (a few hundred tokens each); at the
pricing listed on the review date ($4 per million input tokens, $20 per million output) that is well under one cent.
Generating all 24 tuples costs a few cents. Check the current pricing page before relying on these numbers. Bulk
generation is a reasonable place to try a cheaper model: pass `model="claude-haiku-5-5"` and compare the outputs by
reading them, not by assuming.

## What to notice

- **The top issue is not the one you would have guessed.** Most people expect tone to dominate a support bot's
  problems because it is the most visible. In this sample, invented features and missed handoffs are far more common
  and far more harmful.
- **Frequency and priority are different lists.** Ranked by count, tone (4 traces) beats wrong_policy (3). Weighted by
  severity, wrong_policy jumps ahead. The severity numbers are a judgment; the report says so, and you should be
  able to defend them to your team.
- **36 traces is a start, not a measurement.** One trace moves a rate by about 2.8 points. Use this to decide what to
  fix and what to test next, not to claim the bot is "64 percent broken." Week 3 covers how many cases you need to
  compare two versions.
- **Synthetic inputs need reading too.** Check that each generated message really matches its tuple (a "frustrated"
  message that reads as calm doesn't test what you think). Synthetic data also can't tell you how often a failure
  happens in production; only real traces can.
