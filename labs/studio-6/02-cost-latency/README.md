# Lab 02: Measure a baseline, add prompt caching, compare

**Goes with:** Studio 6, week 2 (lessons 4 to 6). **Time:** about 75 minutes.

## Goal

Build a small measurement harness and use it the way a working engineer would before claiming a win:

1. Price every response from its `usage` meters (uncached input, cache writes, cache reads, output).
2. Stream each request and record **time to first token**, **time to first text**, and **total time**.
3. Run a **baseline** workload (a shared support handbook plus six questions) and a **cached** workload (the same
   requests with a `cache_control` breakpoint after the handbook), **interleaved** so both arms see the same service
   conditions.
4. Summarize each arm (mean cost, cache read fraction, p50 and p95 latencies), compare them, and check the cached arm
   for the signatures of a silent invalidator.

The handbook in `samples/` is fictional. It is about 1,150 words, on the order of 2,000 tokens (the exact count depends
on the model's tokenizer, and your live run reports it), comfortably above the 512-token minimum cacheable prefix for
Claude Haiku 5.5 listed in the prompt caching docs on the review date.

## Steps

Work in `starter.py`. The tests import from it.

1. **Dollars.** Write `request_cost` and `total_input`. Price one-hour writes from the `cache_creation` breakdown when
   it is present. Unknown models must raise `KeyError`: a missing price should never silently cost zero.
2. **Percentiles.** Write `percentile` (nearest rank, as in lesson 6).
3. **Requests.** Write `build_request`. The two arms must differ **only** by the `cache_control` marker, and the system
   prompt must be byte-identical across questions. The tests check both.
4. **Timing.** Write `timed_call` and `run_comparison`. Take timestamps inside the event loop (`message_start`, then
   the first `text_delta`), and read `stream.get_final_message()` for the usage. The tests drive your code with a fake
   streaming client and a fake clock, so the expected times are exact.
5. **Analysis.** Write `summarize` and `cache_health`. `compare` and `format_report` are provided.
6. Run the offline tests until they pass:

   ```bash
   cd labs && source .venv/bin/activate
   pytest studio-6/02-cost-latency -q
   ```

7. With a key in `labs/.env`, run the live test and the script:

   ```bash
   pytest studio-6/02-cost-latency -q -m live -s
   python studio-6/02-cost-latency/starter.py
   ```

No packages beyond `labs/requirements.txt` are needed.

## The fixtures

`fixtures/comparison.json` and `fixtures/broken_cached_arm.json` are **synthetic** records in exactly the shape your
`timed_call` produces, with usage numbers shaped like Haiku 5.5 responses to a workload like this one (a cached prefix of a few
thousand tokens, short questions, a few hundred output tokens). They are not recordings of a real run, and their token
counts won't match yours exactly; they exist so the analysis
code can be tested offline and deterministically. The broken fixture shows what a timestamp in the system prompt
looks like in the meters: a full cache write on every request and no reads.

When you run the live workload, save your own records (`json.dump(records, ...)`) and compare them with the fixture.

## Expected cost

Offline tests: free. The live test sends 8 requests (4 questions, both arms) to `claude-haiku-5-5`; the script sends
12. At the prices in `starter.py` (snapshot of 2026-11-11: $0.10 per million input tokens, $0.50 per million output)
that is well under one cent. Check the [pricing page](https://platform.claude.com/docs/en/about-claude/pricing) before
you rely on the numbers. To try a larger model, change `MODEL` to `claude-sonnet-5-5`; expect a few cents.

## What to notice

- **Cost falls more than latency.** On a prefix of a few thousand tokens, caching cuts the input bill sharply but
  changes time to first token only a little, and total time hardly at all, because output generation dominates.
  Anthropic's latency cookbook reports the same pattern on short tasks, and a much larger time-to-first-token gain on
  a 146,000-token prompt. Try pasting the handbook in five times (still under Haiku's 100,000-token price threshold)
  and see whether the gap grows.
- **Output becomes the bill.** Once the prefix is cached, look at what is left of each request's cost. On Haiku 5.5 a
  cache read costs a tenth of base input, and output costs five times base input, so a few hundred output tokens
  dominate. The next lever is the answer's length, not the prompt.
- **The first cached request costs more.** It pays the 1.25 times write premium. `summarize` includes it, which is
  honest; a report that drops the cold request overstates the saving on low-traffic routes.
- **Same-run comparison.** `run_comparison` alternates which arm goes first. Run it twice and look at how much the
  baseline's own p50 moves between runs: that is your noise floor. Six questions is enough to see the cost effect
  (it's arithmetic), but not enough to make claims about p95 (lesson 6), so treat the latency ratios as a direction.
- **First text arrives after thinking.** Haiku 5.5 thinks adaptively by default, and with the default thinking display
  the thinking streams as empty blocks. Compare `ttft_s` with `first_text_s` to see how much of the wait is thinking.
- **Break it on purpose.** Add `datetime.now().isoformat()` to `INSTRUCTIONS` inside `build_request`, rerun the live
  workload, and confirm `cache_health` reports the invalidator. Then remove it. That is the standing check you'd keep in
  CI for a real service.
- **Refusal fallbacks.** Claude Haiku 5.5 has no server-side refusal fallback, and this lab doesn't need one; if you
  switch to Sonnet 5.5 or Opus 5.5 for production work, read the refusals and fallback docs.
