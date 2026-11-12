# Lab 01: your first streaming call, cost, and retries

**Goal.** Write the small set of functions every model call in this program will go through:
stream a reply, check that it finished, price it, and retry only what is transient.
Lesson: *Your first API calls* (s1-w1-l2).

**Time.** About 45 minutes. **Needs.** Python 3.10+, the shared lab setup
(`labs/README.md`). An Anthropic API key is optional: every offline test runs without one.

## Steps

Work in `starter.py`. After each step, run the tests and watch the failures shrink:

```bash
cd labs && source .venv/bin/activate
pytest studio-1/01-first-call -q
```

1. **`stream_reply`.** Call `client.messages.stream(...)` with `model`, `max_tokens`, and a
   one-message `messages` list (add `system` only when given). Iterate `stream.text_stream`,
   record the time of the first chunk, then call `stream.get_final_message()` for the stop
   reason and usage. Return the dict described in the docstring. Use the injected `clock`
   for timing so the tests are deterministic.
2. **`cost_usd`.** Price all four usage fields at their own rates. Note that with prompt
   caching, `input_tokens` counts only the tokens after the last cache breakpoint, so the
   three input fields are separate quantities, not overlapping ones.
3. **`require_complete`.** Turn `stop_reason` into a decision: return text for `end_turn`
   and `stop_sequence`, raise `TruncatedError` for `max_tokens` and
   `model_context_window_exceeded`, raise `RefusalError` for `refusal`.
4. **`is_retryable` and `backoff_delay`.** Classify SDK exceptions (catch the typed classes;
   never match on message strings) and implement full-jitter backoff.
5. **`with_retries`.** Combine them. Make at most `max_attempts` calls, sleep between
   attempts, honor `retry-after`, and re-raise non-retryable errors immediately.

Then try it for real:

```bash
python studio-1/01-first-call/starter.py
```

The `__main__` block constructs the client with `max_retries=0`. The SDK already retries
connection errors, 408, 409, 429, and 5xx responses twice by default; turning that off here
lets you see your own wrapper work. In production code, pick one retry layer, not two
stacked ones, or your worst-case wait multiplies.

## Live tests and cost

With `ANTHROPIC_API_KEY` in `labs/.env`, two live tests run on `claude-haiku-5-5`: one short
reply and one deliberately truncated reply (`max_tokens=20`). At the prices on the pricing
page at time of writing (USD 0.10 input and 0.50 output per million tokens for prompts up to
100,000 tokens), both together cost well under one cent.

## What to notice

- **TTFT versus total time.** Print both for a short prompt and for "write 400 words about
  X". Total time grows with output length; time to first token barely moves.
- **Output tokens versus visible text.** Compare `usage["output_tokens"]` with a rough token
  estimate of the text you received. Current Claude models think before answering, and
  thinking tokens are billed as output even when their text is not returned.
- **The truncated call returned HTTP 200.** Nothing raised until `require_complete` looked at
  `stop_reason`. That is the check that keeps half-written JSON out of your database.
- **Your key never appears in the code.** `anthropic.Anthropic()` reads `ANTHROPIC_API_KEY`
  from the environment. Keep it in `labs/.env` (gitignored). If a key is ever committed,
  revoke it in the Console; deleting the commit is not enough.

## Sources

Claude docs: [Streaming](https://platform.claude.com/docs/en/build-with-claude/streaming),
[Handling stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons),
[Errors](https://platform.claude.com/docs/en/api/errors),
[Rate limits](https://platform.claude.com/docs/en/api/rate-limits),
[Pricing](https://platform.claude.com/docs/en/about-claude/pricing).
Backoff with jitter: Marc Brooker, [Exponential Backoff And Jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/).
