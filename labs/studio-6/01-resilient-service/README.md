# Lab 01: A resilient LLM service

**Goes with:** Studio 6, week 1 (lessons 1 to 3). **Time:** about 90 minutes.

## Goal

Wrap a Claude call in a small web service that keeps behaving sensibly when the model provider does not:

1. **Classify failures** from the SDK into three kinds: transient (retry), permanent (don't), and refusal (try another model).
2. **Retry with capped exponential backoff and full jitter**, honoring `retry-after`, inside one overall deadline.
3. **Trip a circuit breaker** per model after consecutive failures, so a dead dependency fails fast.
4. **Fall back** from `claude-opus-5-5` to `claude-sonnet-5-5`, and **degrade gracefully** to a static message when both are down.
5. **Stream** the reply as server-sent events, falling back only before the first token reaches the user.

All resilience logic talks to a two-method `ModelClient` interface. The tests drive it with a fake client and a
**fake clock**, so you can test an hour of retries, timeouts, and breaker resets in milliseconds, with no API key.

## Setup

The shared lab environment covers the core lab. The HTTP layer is optional and needs FastAPI:

```bash
cd labs && source .venv/bin/activate
pip install "fastapi>=0.115" httpx uvicorn      # optional: HTTP tests and running the service
```

Without FastAPI, the two HTTP tests are skipped and everything else still runs.

## Steps

Work in `starter.py`. The tests import from it. Fill in the TODOs in this order, running the tests as you go:

```bash
pytest studio-6/01-resilient-service -q
```

1. **`classify_exception`.** Map SDK exceptions to `TransientError`, `PermanentError`, or pass-through lab errors.
   The rules in the docstring come from the Claude API errors and rate-limits pages. Note the special case: the
   monthly spend-cap response is a 429, but it carries no `retry-after` and keeps failing, so it is permanent.
2. **`RetryPolicy.backoff_delay`.** Full jitter: a uniform draw between zero and a capped exponential ceiling.
3. **`call_with_retries`.** Bounded attempts, per-attempt timeouts that shrink to fit the deadline, `retry-after`
   as a minimum wait, and no sleeping past the deadline.
4. **`CircuitBreaker`.** Closed, open, half-open with exactly one trial call.
5. **`ResilientLLM.complete`.** The model chain under one shared deadline, with notes saying why a fallback happened.
6. **`ResilientLLM.stream_events`.** The same chain for streams. Once any text has been sent, never switch models:
   report an `error` event instead, with `discard_partial: true` for a mid-stream refusal.

`AnthropicModelClient`, `format_sse`, and `create_app` are written for you. Read them: the adapter turns SDK
retries off (`max_retries=0`) because this service retries at exactly one layer, and it opts into Anthropic's
server-side refusal fallback (`fallbacks: "default"` with the `server-side-fallback-2026-07-01` beta) on the
models that support it. Your client-side chain then handles outages and overload; the server handles refusals
within one call, and your `Refused` branch covers whatever still comes back refused.

## Run it

With a key in `labs/.env`, FastAPI and uvicorn installed, and your TODOs done:

```bash
cd studio-6/01-resilient-service
uvicorn serve:app --reload
# in another terminal
curl -s localhost:8000/healthz
curl -s localhost:8000/chat -H 'content-type: application/json' -d '{"message": "One sentence on circuit breakers."}'
curl -N localhost:8000/chat/stream -H 'content-type: application/json' -d '{"message": "Count to ten slowly."}'
```

`curl -N` turns off curl's output buffering so you see events arrive. To watch the fallback work, temporarily set
an invalid primary model id in `build_default_app` and notice which error kind that produces (it is a 404, so it
should *not* fall back: a typo is a bug, not an outage).

## Live tests and cost

```bash
pytest studio-6/01-resilient-service -q -m live -s
```

The live test makes one short non-streaming call and one short streaming call to `claude-haiku-5-5` with
`max_tokens=64`. At the pricing listed on the review date ($0.10 per million input tokens, $0.50 per million
output) that is far below one cent. Check the current pricing page before relying on that number.

## What to notice

- **Retries multiply.** The SDK already retries twice by default. If you also retry in your code, and your caller
  retries you, one user click can become 27 upstream calls. Pick one layer. This lab picks the service layer and
  turns SDK retries off.
- **A timeout is not one number.** A float timeout on the SDK bounds each network read, the gap between chunks, not
  the whole stream. That is why `stream_events` also checks the total deadline itself.
- **Fallbacks change behavior.** The Sonnet reply is a different model's answer. The `notes` and `model` fields
  exist so your logs and your evals can tell the two apart. In week 3 you'll send these to traces.
- **Refusals are not outages.** A refusal arrives as a normal response with `stop_reason: "refusal"`. Counting it as
  a breaker failure would let a handful of refused prompts take the primary model offline for everyone.
- **Synchronous on purpose.** The service is synchronous to keep the lab readable. FastAPI runs sync endpoints and
  sync generators in a thread pool. A high-concurrency service would use `AsyncAnthropic` and async generators.
