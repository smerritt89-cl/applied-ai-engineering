# Lab 02: Calibrate an LLM judge against human labels

**Goes with:** Studio 3, week 2 (lessons 5 and 6). **Time:** about 75 minutes.

## Goal

Build a binary LLM judge, then find out how far to trust it:

1. Split 40 human-labeled examples into **dev** and **test**, stratified by label and deterministic.
2. Write the agreement metrics: confusion counts, accuracy, **true positive rate (TPR)**, **true negative rate (TNR)**, and **Cohen's kappa**.
3. Write the judge: Claude with **structured outputs** (`client.messages.parse` with a Pydantic `Verdict`), critique first, then `pass` or `fail`.
4. Improve the judge prompt on **dev only**. Report **test once**, after you stop changing the prompt.
5. Use the judge's measured error rates to **correct a pass rate** (the Rogan and Gladen estimator from lesson 6).

## The data (all fictional)

- `data/policy.txt`: a short returns policy for a made-up outdoor store, "Tallow & Pine Outfitters".
- `data/labeled.jsonl`: 40 customer questions with a support reply each. A person labeled every reply `pass` or `fail`
  against one criterion and wrote a one-line critique. 24 pass, 16 fail.
- `data/recorded_judge.jsonl`: verdicts for every example from two judge prompts, `v1` (a vague "is this a good
  answer?" prompt) and `v2` (the criterion written as checkable conditions). **These were written for this lab to
  behave the way weak and improved judges typically do, so the offline tests have known answers. They were not
  captured from a real model.** Your live run replaces them with real outputs.

**The criterion.** PASS only if the reply (1) answers the customer's actual question, or says the policy doesn't cover
it and escalates without guessing, and (2) makes no policy claim the excerpt doesn't support. Length and tone don't
count. Several replies are long, warm, and wrong; several are short and right. That mix is deliberate: it is where
verbosity bias shows up.

## Steps

Work in `starter.py`. The tests import from it.

1. **Split.** `split_dev_test`: within each label, order by `sha256(f"{seed}:{id}")` and send the first
   `round(n * test_fraction)` to test. Hashing the id (instead of `random.shuffle`) makes the split identical on every
   machine and independent of file order, so nobody can quietly reshuffle until the numbers look good.
2. **Metrics.** `confusion`, `cohen_kappa`, `agreement_metrics`, `score_judge`, `corrected_pass_rate`. Docstrings give
   the formulas. "Positive" means `pass`. Refusals and truncations are excluded and counted, never scored as `fail`.
3. **Judge.** Fill in `Verdict` (critique first) and `judge`. Use exactly this call shape:

   ```python
   response = client.messages.parse(
       model=model,
       max_tokens=MAX_TOKENS,
       system=JUDGE_SYSTEM,
       messages=build_judge_messages(policy, example.question, example.reply),
       output_format=Verdict,
       output_config={"effort": JUDGE_EFFORT},
   )
   ```

   Check `response.stop_reason` for `refusal` and `max_tokens` before reading `response.parsed_output`.
4. Run the offline tests until they pass:

   ```bash
   cd labs && source .venv/bin/activate
   pytest studio-3/02-judge-calibration -q
   ```

5. With a key in `labs/.env`, run the judge on dev, read every disagreement, and edit `JUDGE_SYSTEM`. Repeat:

   ```bash
   python studio-3/02-judge-calibration/starter.py
   ```

6. When you stop editing the prompt, run the held-out report once, and the live test:

   ```bash
   python studio-3/02-judge-calibration/starter.py --test
   pytest studio-3/02-judge-calibration -q -m live -s
   ```

## Design notes

- **Structured outputs, critique first.** `messages.parse` sends your Pydantic schema as `output_config.format` and
  validates the reply. Claude's docs say required properties keep their schema order in the output, so declaring
  `critique` before `verdict` makes the judge write its reasons before it commits. The critique is also what you read
  when the judge disagrees with a person.
- **Effort is set explicitly.** Current Claude models think adaptively and differ in their default effort, so the lab
  pins `JUDGE_EFFORT`. Changing it changes the judge, which means re-calibrating.
- **No sampling parameters.** `temperature`, `top_p`, and `top_k` are rejected on the current API version; a fake
  client in the tests checks that you don't send them.
- **No server-side refusal fallback.** Elsewhere in this course, Claude Opus 5.5 code can opt into a fallback that
  re-runs a declined request on another model. A judge is a measuring instrument: if some verdicts silently came from a
  different model, your calibration numbers would describe a mixture. Here a refusal is recorded as an error and
  counted instead.
- **A judge from a different family.** The replies here were written by hand, so self-preference isn't in play. In a
  real system, if the replies come from Claude, consider calibrating a GPT, Gemini, or open-weight judge on the same
  labels and comparing TPR, TNR, and cost (lesson 5). Keep the metric code; only `judge` changes.

## Expected cost

Offline tests: free. A full dev or test run is 20 judge calls on `claude-opus-5-5` with roughly 700 input tokens each.
Output cost depends mostly on how many thinking tokens the judge spends at the chosen effort; at the review-date price
($4 per million input tokens, $20 per million output) expect well under a dollar for dev plus test. To compare a
cheaper judge, pass `model="claude-haiku-5-5"` to `run_judge` and calibrate it the same way. Check the current pricing
page before you rely on these numbers.

## What to notice

- **v1 looks fine until you split the metrics.** On dev, the recorded v1 judge passes most replies. Its TNR is close to
  zero: it almost never catches a bad reply. Its kappa is below zero. Accuracy alone would have hidden that on a set
  with more passes.
- **Dev flatters you.** The recorded v2 prompt scores a little lower on test than on dev. That gap is the reason the test
  split exists, and with 20 examples per split each number has wide error bars (lesson 6 computes them).
- **Disagreements are data.** Read the critiques where the judge and the person disagree. Some will show a judge
  mistake; some will show a label you'd now change (criteria drift). If you relabel, relabel before you look at test.
- **The correction is only as good as the rates.** `corrected_pass_rate` uses TPR and TNR measured on 20 examples. Try
  perturbing each by 0.05 and watch the estimate move.
