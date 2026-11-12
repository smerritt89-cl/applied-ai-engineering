# Lab 04: Evaluate a RAG system, then write the report

**Goes with:** Studio 3, week 4 (lessons 11 and 12). **Time:** about 75 minutes.

## Goal

Score a small RAG system the way you will score your own in the Studio 3 project, and turn the numbers into a
one-page report a non-engineer can act on:

1. **Retrieval metrics** against hand-labeled relevant chunks: recall@k, precision@k, and MRR.
2. **Faithfulness**: split each answer into claims, have a judge decide whether each claim is supported by the
   retrieved passages, and score the fraction supported. Abstentions are counted separately, not as faithful answers.
3. **Check the judge** against a domain expert's labels (TPR and TNR, from week 2).
4. **Uncertainty**: a percentile bootstrap interval on mean faithfulness (week 3).
5. **The report**: a fixed structure, plain-language bottom line first.

The data in `fixtures/` is fictional: eight questions about a company handbook, the ranked chunks a retriever
returned, the answers a model wrote, and labels.

| File | What it holds |
|---|---|
| `fixtures/rag_outputs.json` | chunks, and for each question: retrieved ids (ranked), relevant ids (labeled), answer, abstained flag |
| `fixtures/recorded_judgments.json` | illustrative judge verdicts per claim, so offline tests are deterministic (not real model output) |
| `fixtures/human_labels.json` | a domain expert's supported or unsupported label for every scored claim, with notes on the disagreements |

## Steps

Work in `starter.py`. The tests import from it.

1. **Retrieval.** Write `recall_at_k`, `precision_at_k`, `reciprocal_rank`, and `retrieval_metrics`. Follow the
   docstrings exactly: precision divides by k even when fewer items came back, and recall raises on an empty
   relevant set, because "recall of nothing" is undefined, not 1.0.
2. **Claims.** Write `split_claims`. The two regular expressions you need are defined above it. The recorded
   judgments are keyed by the exact claim text, so `test_recorded_judge_matches_your_claims` tells you if your split
   differs.
3. **Faithfulness.** Write `faithfulness`. Pass the judge the retrieved chunk texts in rank order. Return `None` for
   an abstention and don't call the judge for it.
4. **Judge check.** Write `judge_agreement`.
5. **Bootstrap.** Write `bootstrap_ci` with `random.Random(seed)` so results are reproducible.
6. **The live judge.** Write `judge_claim` using the call shape in the TODO. It uses structured outputs
   (`client.messages.parse(..., output_format=Verdict)`), so the reply is a validated `Verdict` with a reason and a
   boolean. The `reason` field comes first so the model states its evidence before its verdict.
7. **The report.** Write `build_report`. The docstring lists the required sections and their order.
8. Run the offline tests until they pass, then generate the report:

   ```bash
   cd labs && source .venv/bin/activate
   pytest studio-3/04-rag-eval -q
   python studio-3/04-rag-eval/starter.py          # recorded judgments, writes report.md
   ```

9. With a key in `labs/.env`, run the live test and a live evaluation:

   ```bash
   pytest studio-3/04-rag-eval -q -m live -s
   python studio-3/04-rag-eval/starter.py --live   # judges all 16 claims with Claude, saves live_judgments.json
   ```

## Expected cost

Offline tests: free. The live test makes two judge calls; `--live` makes one call per claim (16 calls), each a few
hundred input tokens plus the judge's reasoning. At the prices on the Claude pricing page on the review date
(`claude-opus-5-5`: $4 per million input tokens, $20 per million output), the full live run costs a few cents.
Thinking tokens are billed as output, so check `usage` on real responses rather than trusting this estimate, and
check the current pricing page.

To compare judges, change `JUDGE_MODEL` (for example to `claude-haiku-5-5`) and rerun `--live`. A cheaper judge is
fine if it agrees with the human labels as well as the expensive one does. That is a measurement, not a guess.

## What to notice

- **The judge is lenient, and the report says so.** The recorded judge accepts every supported claim (TPR 1.00) but
  catches only half of the unsupported ones (TNR 0.50). Look at `human_labels.json` for the two it missed: q4 turns
  "remote work with manager approval" into permission to work abroad, and q5 turns "can be remotely wiped" into a
  promise. Faithfulness of 0.90 from this judge overstates the truth (the human labels give about 0.76). Week 2's
  correction (lesson 6) is how you would adjust it.
- **Retrieval failures become generation failures.** q4's answer is unfaithful because the passage that answers the
  question (`rem-2`) was never retrieved, so the model filled the gap. Fix retrieval before you tune the answer
  prompt. This is why you report the two halves separately.
- **Faithful is not correct.** q8 says "Yes" to "Do I need approval to take a week off?" and cites a passage about
  requests of *more than* 5 consecutive working days. Every claim is supported, the faithfulness score is 1.0, and the
  answer may well be wrong for a standard five-day week. Catching that needs a reference answer and a correctness
  grader, which the Studio 3 project asks for.
- **Abstention is its own outcome.** q6 abstained because retrieval missed the parental-leave chunk. That is the right
  behavior given what was retrieved, and the wrong outcome for the user. Count abstentions separately, and track
  whether they happen on questions the corpus can answer.
- **Eight questions is not enough.** Read the interval in your report. It is wide, so this eval could not tell two
  systems apart unless they differ a lot. Your project set should be larger.
- **Refusal fallbacks.** Anthropic offers a beta server-side fallback that re-runs a declined request on another model.
  It is left out here to keep the judge call simple; a production judge should handle `refusal` (this one raises
  `JudgeFailed`) and log how often it happens.
