# Lab 02: a model bake-off on your own prompts

**Goal.** Run the same prompts through two or more models, record quality, latency, tokens,
and cost for each, and make a recommendation you can defend with numbers.
Lesson: *Tokens, cost, latency, and choosing a model* (s1-w1-l3).

**Time.** About 60 minutes. **Needs.** The shared lab setup (`labs/README.md`) and an
Anthropic API key for the live run. Every offline test runs without a key.

## What is provided, and what you write

`starter.py` already contains the provider adapters, the command-line interface, and CSV
re-scoring. You write the harness logic, which is the part that decides whether your
conclusion is trustworthy:

1. `cost_usd`: price one call from the dated `PRICES` table.
2. `run_one` and `run_bakeoff`: time each call, and turn failures into data (an `error`
   string) instead of crashing the run. A model that times out on one prompt in eight is a
   finding, not a bug in your harness.
3. `auto_score`: a crude keyword check per prompt (`must_include` in `prompts.json`). It
   catches gross failures. It is not a quality judgment.
4. `percentile` and `summarize`: per-model mean score, error count, cost per task, p50 and
   p95 latency, and mean output tokens.
5. `pick_winner`: the cheapest model with zero errors whose mean score clears your quality
   bar, breaking ties on p95 latency.
6. `write_csv`: one row per (prompt, model), with an empty `human_score` column for you.

```bash
cd labs && source .venv/bin/activate
pytest studio-1/02-model-bakeoff -q
```

## Run it

```bash
python studio-1/02-model-bakeoff/starter.py                      # Claude Sonnet 5.5 vs Haiku 5.5
python studio-1/02-model-bakeoff/starter.py --models claude-opus-5-5 claude-haiku-5-5
```

Other providers join automatically when their key is in `labs/.env` **and** the optional
`openai` package is installed (`pip install openai`). The adapters follow each provider's
documented quickstart at time of writing:

| Provider | Key | How the adapter calls it |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | Official `anthropic` SDK, Messages API |
| OpenAI | `OPENAI_API_KEY` | Official `openai` SDK, Responses API |
| Google Gemini | `GEMINI_API_KEY` | `openai` SDK against Gemini's OpenAI-compatible endpoint (marked beta in Google's docs) |
| xAI Grok | `XAI_API_KEY` | `openai` SDK, Responses API at `https://api.x.ai/v1`, as xAI's docs show |

Compatibility layers do not expose every native feature (for example, Gemini's page lists
caveats about reasoning settings and batch), so for production use each provider's own
SDK and docs. Model ids for the optional providers are in `OPTIONAL_MODELS`; check them
against the providers' model pages before you run, because they change often.

## Score it by hand

Open `results.csv` in a spreadsheet. For each row, read the output and fill `human_score`
with a number from 0 to 1 using the rubric in `RUBRIC.md`. Do it **blind** if you can: hide
the `model` column while you score. Then re-summarize without calling any API:

```bash
python studio-1/02-model-bakeoff/starter.py --rescore studio-1/02-model-bakeoff/results.csv --bar 0.8
```

Finish with a short paragraph: which model you would ship for these prompts, at what cost
per task and p95 latency, what it got wrong, and what evidence would change your mind.

## Cost of the live run

Eight prompts on Sonnet 5.5 and Haiku 5.5, with typical output lengths, cost under ten US
cents at the prices listed on the Claude pricing page at time of writing. Adding Opus 5.5
adds roughly twice the Sonnet share, since its per-token prices are twice Sonnet's. Optional providers bill on their own accounts. The script prints the
total after each run.

## What to notice

- **Auto-scores and human scores disagree.** Find a row where the keyword check passed but
  the answer is wrong, and one where it failed but the answer is fine. That gap is why
  Studio 3 spends weeks on evaluation.
- **Output tokens drive both cost and latency.** Sort by `output_tokens`; latency mostly
  follows. Current Claude models think before answering and thinking is billed as output,
  so compare `output_tokens` with the length of the visible text.
- **Eight prompts is a small sample.** A one-prompt difference is 12.5 points of mean score.
  Treat small gaps as ties, and add prompts from your real work before deciding anything
  that matters.
- **The provider's reputation never appears in the CSV.** Only your prompts, your rubric,
  and the measured numbers do. That is the point.

## Sources

[Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing),
[Choosing a Claude model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model),
[OpenAI pricing](https://developers.openai.com/api/docs/pricing),
[Gemini pricing](https://aistudio.google.com/docs/pricing),
[Gemini OpenAI compatibility](https://aistudio.google.com/docs/openai),
[xAI models and pricing](https://docs.x.ai/docs/models).
