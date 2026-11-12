# Lab 04 (Studio 5): Benchmark your model against a frontier model

**Goes with:** Studio 5, week 4 (lessons 10 to 12). **Time:** about 60 minutes. **Needs:** the shared lab setup
(`labs/README.md`). No API key and no GPU: everything runs on recorded predictions.

## Goal

You fine-tuned a small open model with LoRA to extract action items. Before anyone believes "the small model is as
good as the frontier model," you need a benchmark that would survive a skeptical review. Three recorded runs on the
same frozen test set are in `fixtures/`:

| System | What it stands for |
|---|---|
| `ft-lora` | A small open model plus your LoRA adapter, served on one rented GPU |
| `base` | The same small model without the adapter, same serving setup |
| `frontier` | A frontier model called through a provider API, with a few-shot prompt |

Turn them into a report with:

1. **Per-field accuracy** (is it an action item, owner, due date, priority) and **exact match** (every field right).
2. **Integrity checks** that refuse to score a run made on a different test set, a run with duplicate ids, or a run
   with cases missing. Unparseable outputs stay in the denominator.
3. A **bootstrap interval** for each system's exact match and a **paired bootstrap interval** for each system's
   difference from the reference (Studio 3, lesson 7).
4. **Cost per 1,000 tasks**: from token counts and list prices for the API, and from GPU hourly price, measured
   throughput, and utilization for self-hosting.
5. **Latency** at p50 and p95, and a **Markdown report**.

## Files

| File | What it is |
|---|---|
| `fixtures/test_set.jsonl` | 150 frozen cases: a meeting snippet and gold labels for four fields. |
| `fixtures/ft-lora.json`, `base.json`, `frontier.json` | Recorded predictions with latency and token counts. |
| `fixtures/ft-lora-stale.json` | The same run, recorded against an older version of the test set. Your code must refuse it. |
| `fixtures/costs.json` | Prices and serving assumptions for each system (a dated snapshot; see the note inside). |
| `fixtures/make_fixtures.py` | Regenerates everything deterministically. |
| `starter.py` | Your file. Functions marked `TODO`. The tests import from it. |
| `solution.py` | A reference implementation. Try for 20 minutes first. |

**The data is synthetic.** The error rates were invented to make the analysis interesting. Nothing here measures
any real model, so don't quote these numbers as evidence about small or frontier models.

Each prediction is `{"id", "output", "latency_s", "input_tokens", "output_tokens"}`, where `output` is the parsed
extraction (`{"is_action_item", "owner", "due_date", "priority"}`) or `null` when the model's reply did not parse or
failed schema validation. Each run also records the model, the prompt version, the serving setup, and the test set's
fingerprint: a hash of every case's id, input, and gold labels.

## Steps

Work in `starter.py`, in this order. Each function's docstring is the spec.

1. `normalize` and `field_correct`. Case and surrounding whitespace are formatting; anything else is an error.
   A `null` output is wrong on every field.
2. `score_run`. Check the fingerprint first, then duplicates, then that the ids match the test set exactly.
3. `field_accuracy`, `exact_match`, `parse_rate`.
4. `bootstrap_ci` and `paired_bootstrap_diff`. Follow the resampling recipe in the docstring so results are
   reproducible; the paired version resamples the same case indices for both systems.
5. `api_cost_per_1000`, `selfhost_cost_per_1000`, `cost_per_1000`, `latency_summary`.
6. `render_report`.

Run the tests until they pass:

```bash
cd labs && source .venv/bin/activate
pytest studio-5/04-benchmark -q
```

Then produce the report:

```bash
cd studio-5/04-benchmark
python starter.py fixtures/test_set.jsonl fixtures/ft-lora.json fixtures/base.json fixtures/frontier.json \
    --costs fixtures/costs.json --reference frontier --out report.md
```

## What to notice

- **"As good as" needs an interval.** The adapter's exact match is about 7 points above the frontier model's, but the
  paired interval runs from roughly zero to about 15 points. The defensible claim is "no worse, and plausibly better,
  on this test set," not "beats the frontier model."
- **Per-field numbers tell you why.** The frontier model is better at detecting items and owners; the adapter is
  better at priority, because priority follows a house convention the adapter learned from labeled examples and the
  frontier model had to infer from a few-shot prompt. That is the typical shape of a fine-tuning win: a narrow,
  learnable convention, not general capability.
- **The base model is the control.** Without the adapter the same small model scores around 43 percent, and more
  than one output in ten fails to parse. That gap is what fine-tuning bought you; report it so nobody mistakes the
  base model's quality for the adapter's.
- **Utilization decides self-hosted cost.** At the recorded 20 percent utilization the adapter costs about $1.33
  per 1,000 tasks, against about $1.94 for the API. Change `utilization` in `costs.json` to 1.0 (a busy, batched
  GPU) and it drops to about $0.27; change it to 0.05 (a GPU idling for occasional traffic) and it rises above $5.
  The API price doesn't move with your traffic. Lesson 11 turns this into a break-even calculation.
- **Latency is a different axis.** The self-hosted model's p95 is well under a second; the API's is above two.
  Whether that matters depends on whether a person is waiting.
- **The integrity checks are the point.** Try scoring `ft-lora-stale.json`, or edit one gold label in a copy of
  the test set. A benchmark that silently scores runs from different test sets, or drops the cases a model failed
  on, can make any system look good.

## Using it in the project

The studio project asks for the same report on your own model. Record each system's predictions in this JSON shape
(one run per system, with the test-set fingerprint written at prediction time), and reuse this file as
`benchmark.py`. If you run each system several times, keep the runs separate and report the spread across them;
don't pool repeated runs as if they were extra cases.

## Expected cost

Free. Nothing in this lab calls a model or rents a GPU.
