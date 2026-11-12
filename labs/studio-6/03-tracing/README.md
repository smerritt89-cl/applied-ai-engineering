# Lab 03 (Studio 6): Trace, log, and chart a two-step LLM workflow

**Goes with:** Studio 6, week 3 (lessons 7 to 9). **Time:** about 75 minutes. **Needs:** the shared lab setup
(`labs/README.md`). No API key for the offline tests.

## Goal

A support desk runs a two-step workflow on every ticket: a small model triages it (`claude-haiku-5-5`, prompt
`triage-v3`), then a large model drafts a reply for a person to review (`claude-opus-5-5`, prompt `reply-v7`). You
will make it observable:

1. **Trace** each run with OpenTelemetry: one root span for the workflow and one `chat {model}` span per model call,
   with attributes from the GenAI semantic conventions (model, prompt version, tokens, finish reason, errors).
2. **Log** one structured JSONL record per call, with a fixed schema, a pseudonymous user id, a computed cost, and
   content that is off by default and **redacted** when you turn it on.
3. **Chart** the log: aggregate cost, error and refusal rates, and latency percentiles, and render a small Markdown
   dashboard you could paste into a weekly review.

## Files

| File | What it is |
|---|---|
| `starter.py` | Your file. Functions and patterns marked `TODO`. The tests import from it. |
| `solution.py` | A reference implementation. Try for 20 minutes first. |
| `test_tracing.py` | Offline tests (redaction, cost, record schema, error paths, aggregation, spans) plus one live test. |
| `samples/tickets.jsonl` | Four fictional tickets with emails, phone numbers, and a fake key in them (reserved example domains and numbers). |
| `samples/sample_log.jsonl` | A synthetic week of traffic: 60 traces with a few errors, refusals, cache hits, and slow calls. |
| `samples/make_sample_log.py` | Regenerates the sample log deterministically. |

## Optional package

The span tests use the OpenTelemetry SDK's in-memory exporter. They are skipped if it isn't installed:

```bash
cd labs && source .venv/bin/activate
pip install opentelemetry-sdk
```

Without the SDK, the OpenTelemetry API (installed with the `anthropic` package) gives you no-op spans, and the code
still runs. The starter also has a no-op stand-in if the API is missing entirely. Use an SDK version that matches the
installed `opentelemetry-api` version (`pip show opentelemetry-api`).

## Steps

Work in `starter.py`, in this order. Each docstring is the spec.

1. **Redaction.** Write `SECRET_PATTERNS`, `SECRET_KV`, `EMAIL`, and `PHONE_PATTERNS`, then `redact` and
   `redact_value`. Redact secrets first, then emails, then phones. The parametrized tests list what must be caught
   and what must be left alone (dates, prices, ticket numbers). Three tests are marked `xfail`: they document known
   false negatives (an obfuscated email, a name, a UK national-format number). Read them; lesson 8 discusses why a
   regex redactor can't close those gaps on its own.
2. **Pseudonyms.** `pseudonymize` with `hmac.new(key, user_id, hashlib.sha256)`. A bare hash of an email can be
   reversed by hashing a list of candidate emails; a keyed hash can't without the key.
3. **Cost.** `cost_usd` from `PRICES_PER_MTOK`. Claude reports uncached input, cache reads, and cache writes as
   separate counts, and each has its own price. An unknown model raises: a silent zero makes a dashboard lie.
4. **Validation.** `validate_record` returns a list of problems. Use it in tests and in a nightly job over real logs.
5. **The traced call.** `call_step` is the heart of the lab. Inside `tracer.start_as_current_span(f"chat {model}")`:
   set the request attributes, time the call with the injected `clock`, call `client.messages.create(...)` with
   exactly `model`, `max_tokens`, `system`, and `messages`, then set the response attributes and write the record.
   On an exception, record it on the span (`record_exception`, `error.type`, error status), write an `error`
   record with zero tokens and cost, and re-raise. Note one trap the tests check: the semantic conventions'
   `gen_ai.usage.input_tokens` **includes** cached tokens, while Claude's `usage.input_tokens` does not.
6. **Aggregation.** `percentile` (nearest rank) and `aggregate`. Failed calls count toward latency.
7. Run the tests until they pass:

   ```bash
   cd labs && source .venv/bin/activate
   pytest studio-6/03-tracing -q
   ```

8. Render the dashboard from the sample log:

   ```bash
   cd studio-6/03-tracing
   python starter.py dashboard samples/sample_log.jsonl --out dashboard.md
   ```

9. With a key in `labs/.env`, run the live test and the live workflow. With `opentelemetry-sdk` installed, the spans
   print to the console through `ConsoleSpanExporter`:

   ```bash
   pytest studio-6/03-tracing -q -m live -s
   python studio-6/03-tracing/starter.py run --capture-content
   python studio-6/03-tracing/starter.py dashboard studio-6/03-tracing/logs/run.jsonl
   ```

## Expected cost

Offline tests: free. The live test runs one ticket through both steps. The live `run` command runs four. With
prompts of a few hundred tokens, at the prices on the review date (Haiku 5.5 at $0.10 and $0.50 per million input
and output tokens, Opus 5.5 at $4 and $20), the whole live part costs well under ten cents. Check the pricing page
before relying on that, and update `PRICES_PER_MTOK` when prices change: a price table is code and needs a version.

## What to notice

- **Two sources of truth, on purpose.** The span carries metadata only (no prompt text). The JSONL record carries the
  same ids plus redacted, opt-in previews. You can send spans to a vendor and keep content in a store with tighter
  access, which is the external-storage pattern the semantic conventions recommend for production.
- **The trace id joins everything.** Each record has the trace id of its span, so a slow row on the dashboard leads
  you to the full trace, and a trace leads you to its records.
- **Count tokens once.** If your installed Anthropic SDK emits its own spans (its OpenTelemetry support is in beta),
  each `chat` span you create will contain an SDK span carrying the same usage. That nesting is fine, but a backend
  query that sums usage over every span counts each call twice. This lab treats the JSONL record as the source of
  truth for cost; decide the equivalent for your own system.
- **Percentiles at small n.** In the sample log, the reply step's p95 is decided by a handful of slow calls. With 56
  calls, nearest-rank p95 is the 54th value. Before you alert on a p95, ask how many calls it rests on.
- **Cost per trace, not per call.** In the sample log, triage costs about a cent per thousand calls and the reply about six dollars per thousand. A
  routing change that saves on triage barely moves the bill. The dashboard makes that visible.
- **What the redactor misses.** Turn on `--capture-content` on the live run and read the previews. Anything a regex
  can't recognize (names, addresses, free-text account details) is still there. That is why content capture stays
  off by default and why access to the content store matters more than the redactor.
- **Refusal fallbacks.** Claude Opus 5.5 supports a beta server-side fallback that re-runs a declined request on
  another model. It is left out here to keep the call simple; if you add it, record which model served each call
  (the response's `model` field), or your cost and quality numbers will mix two models.
