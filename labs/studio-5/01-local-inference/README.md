# Lab 01: Benchmark a local model against Claude

**Goes with:** Studio 5, week 1 (lesson 3, with lessons 1 and 2 as background). **Time:** about 60 minutes.

## Goal

Run a small open model on your own machine, measure it the way an engineer would, and compare it with a Claude
model on one realistic extraction task (a support ticket to five JSON fields).

1. Turn Ollama's timing fields (nanoseconds) into load time, prefill speed, and decode speed.
2. Read a streamed Ollama response and measure **time to first token** (TTFT) correctly.
3. Summarize repeated runs: discard the warm-up, report the median and p90.
4. Parse JSON out of real model replies (plain, fenced, or wrapped in prose) and score it field by field.
5. Optionally, run the same prompt live through Ollama or MLX, and through Claude.

Everything in steps 1 to 4 is tested offline with fixtures in `fixtures/`, so you can finish the core of the lab
without installing a runtime or having an API key.

## Steps

Work in `starter.py`. The tests import from it. The live adapters (`run_ollama`, `run_mlx`, `run_claude`) and the
CLI are written for you; read them, because they show where each number comes from.

1. **Units and rates.** Write `ns_to_s`, `tokens_per_second` (raise `ValueError` for a non-positive duration), and
   `bandwidth_ceiling_tps` (memory bandwidth divided by bytes of weights read per token).
2. **The final chunk.** Write `parse_ollama_final`. Ollama's API reference lists `load_duration`,
   `prompt_eval_count`, `prompt_eval_duration`, `eval_count`, `eval_duration`, and `total_duration`, all durations in
   nanoseconds, and gives decode speed as `eval_count / eval_duration * 10^9`. A cached prompt can have no prefill
   time, so return `None` for a rate whose duration is zero.
3. **The stream.** Write `consume_ollama_stream`. It receives `(seconds_since_request_start, raw_line)` pairs.
   Skip blank lines, raise on an `error` chunk, take TTFT from the first chunk with non-empty `message.content`
   (empty and thinking-only chunks don't count), and raise if the stream ends without a `done: true` chunk.
4. **Statistics.** Write `summarize` with nearest-rank p90.
5. **Parsing.** Write `extract_json`: whole text, then the first code fence, then the first balanced object (the
   brace-matching helper is provided). Lists don't count.
6. **Scoring.** Write `score_fields`: strings compare after collapsing whitespace and casefolding; booleans must be
   real booleans (so `1` is not `true`); a missing field is wrong.
7. Run the offline tests until they pass:

   ```bash
   cd labs && source .venv/bin/activate
   pytest studio-5/01-local-inference -q
   ```

## Running it live (optional)

**Ollama.** Install it from https://ollama.com, then:

```bash
ollama pull llama3.2:3b          # about 2 GB
pytest studio-5/01-local-inference -q -s -k local
python studio-5/01-local-inference/starter.py --backend ollama --runs 5
```

Try a second model too, for example `ollama pull qwen3.5:4b` or `ollama pull gemma4:e4b`, and pass `--model`.
Check the license of each one (lesson 1) before you use it for anything beyond this lab.

**MLX (Apple silicon only).** This needs one extra package, which is not in `labs/requirements.txt`:

```bash
pip install mlx-lm
python studio-5/01-local-inference/starter.py --backend mlx --runs 5
```

The default model is `mlx-community/Llama-3.2-3B-Instruct-4bit` (downloaded from Hugging Face on first use). The MLX
path has no schema-constrained decoding, so the reply is parsed from free text; compare how often that fails with
the Ollama path, which sends the JSON Schema in the `format` field.

**Claude.** With `ANTHROPIC_API_KEY` in `labs/.env`:

```bash
pytest studio-5/01-local-inference -q -m live -s
python studio-5/01-local-inference/starter.py --claude --runs 3
```

`run_claude` streams one request to `claude-opus-5-5` with structured outputs (`output_config.format`) and effort set
to `low`. Pass `--claude-model claude-haiku-5-5` to compare a cheaper tier. Anthropic also offers a beta server-side
fallback for refused requests; it is left out here to keep the call simple.

If neither runtime is installed, the script says so and exits; the local tests are skipped, not failed.

## Expected cost

Offline and local tests: free. The live Claude test sends one prompt of about 200 tokens and gets a short JSON reply,
plus some thinking tokens, which is a fraction of a cent at the Opus 5.5 prices listed on the review date ($4 per
million input tokens, $20 per million output). Check the current pricing page before relying on that.

## What to notice

- **Cold start versus warm runs.** The first Ollama run includes `load_duration`. That is why the script discards a
  warm-up run, and why the test checks that dividing by `total_duration` understates decode speed.
- **TTFT has a definition.** For a reasoning model, the first chunks can be thinking or empty. Decide what
  "first token" means for your users (usually the first visible answer text) and measure that.
- **Tokens per second is per tokenizer.** Claude and Llama count tokens differently, and Claude's `output_tokens`
  includes thinking tokens. Compare seconds per task and accuracy, not raw tokens per second, across families.
- **The bandwidth ceiling.** Compute `bandwidth_ceiling_tps` for your model's file size and your Mac's memory
  bandwidth (Apple's spec page lists it). Your measured decode speed should come in below it. If it doesn't, the
  measurement is wrong.
- **Valid is not correct.** The fixture `local_reply.txt` parses and fits the schema, and still gets
  `refund_requested` wrong. A schema constrains shape; only scoring against labels tells you about accuracy. One
  ticket is an anecdote: build 20 to 50 labeled tickets before you decide anything, which week 4 does properly.
