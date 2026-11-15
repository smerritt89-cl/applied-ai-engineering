# Walkthrough: trace, log, and chart a two-step LLM workflow

## What this code does

`solution.py` makes a small support-desk workflow observable. Every ticket goes through two model
calls: a cheap model triages it into a category, then a larger model drafts a reply for a person
to review. The code wraps each call in an **OpenTelemetry span** (a timed, structured record of
one step, nested under a root span for the whole workflow), writes one **structured log record**
per call (a JSON line with a fixed schema, a computed cost, a pseudonymous user id, and optional
redacted previews of the text), and turns a log file into a **Markdown dashboard** of cost, error
rates, and latency.

The file reads top to bottom in the order you'd build it: constants and prices; a fallback so
tracing works even without the OpenTelemetry package; redaction and pseudonyms; cost; the record
schema and its validator; the traced model call; the two-step workflow; aggregation and the
dashboard; and a small command-line interface.

Two design ideas are worth taking away. First, **spans carry metadata, logs carry content**: no
prompt or reply text ever goes on a span, while the log can hold redacted previews, only if you
opt in. You can send spans to a vendor and keep content somewhere with tighter access. Second,
**the trace id joins everything**: every log record carries the id of its trace, so a slow row on
the dashboard leads straight to the trace, and the trace leads to its records.

## How to read this lab

Open `work.py` beside this page. It starts as a copy of `solution.py`, so the line numbers below
match it until you change something. Read a section here, then the code it points to.

Run the tests from VS Code's **Testing** panel (the flask icon): expand `studio-6/03-tracing` and
press the run button. Everything except the one `live` test runs without an API key. The span
tests need `opentelemetry-sdk` and are skipped without it (see the README); three redaction tests
are marked `xfail` on purpose, documenting known gaps. To see a test fail on purpose, swap the
email and phone steps in `redact`, rerun, read the message, and undo it.

## Imports and the workflow's constants (lines 13 to 53)

```python
from __future__ import annotations
...
SCHEMA_VERSION = 1
WORKFLOW = "support_reply"
TRIAGE_MODEL = "claude-haiku-5-5"
TRIAGE_PROMPT_VERSION = "triage-v3"
...
PRICES_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.00, "cache_write_5m": 5.00, "cache_read": 0.20, "output": 20.00},
    ...
}
```

- `from __future__ import annotations` (line 13) lets the file use newer **type hint** syntax,
  like `str | None` ("a string or `None`"), on older Python versions. Hints describe what goes in
  and out of functions; they don't change behavior.
- Everything imported is standard library: `hmac` and `hashlib` for pseudonyms, `secrets` for
  random ids, `re` for redaction patterns, `argparse` for the command line, `contextlib` for the
  no-op tracer.
- `SCHEMA_VERSION` (line 30) goes into every log record. When the record's shape changes, you bump
  it, and anything reading old logs can tell which shape it's looking at.
- Each model has a **prompt version** next to it (`triage-v3`, `reply-v7`). Recording the version
  on every call is what lets you answer "did the new prompt make replies slower or more expensive?"
  from the log alone.
- `PRICES_PER_MTOK` is the price table, dated in a comment. The README calls it code that "needs
  a version" for a reason: when prices change, old cost numbers stay right only if you know which
  table produced them.

## Tracing that works without the SDK (lines 57 to 107)

```python
try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.trace import Status, StatusCode
except ImportError:
    _otel_trace = None
...
def get_tracer(name: str = "aae.lab.tracing"):
    if _otel_trace is None:
        return _NoopTracer()
    return _otel_trace.get_tracer(name)
```

- The `try` / `except ImportError` (lines 57 to 61) is an **optional import**: if the OpenTelemetry
  API isn't installed, the module still loads and `_otel_trace` is `None`.
- `_NoopSpanContext`, `_NoopSpan`, and `_NoopTracer` (lines 64 to 87) are stand-ins with the same
  method names as the real thing, which do nothing. `@contextlib.contextmanager` turns the generator
  function `start_as_current_span` into something usable in a `with` statement: code before `yield`
  runs on entry, and the yielded value is what `as span` receives. This is the **null object
  pattern**: the rest of the code never has to check "is tracing on?".
- `_mark_error` (lines 97 to 100) records an exception on a span and, when the real API is present,
  sets the span's status to ERROR with the exception's class name.
- `_ids` (lines 103 to 107) returns the span's trace and span ids as hex strings.
  `f"{ctx.trace_id:032x}"` is an **f-string format spec**: hexadecimal (`x`), padded with zeros to
  32 characters, which is the standard way trace ids are written. When tracing is a no-op the span
  context is invalid, so it falls back to random ids from `secrets.token_hex` (16 bytes gives 32 hex
  characters), so records still have ids to join on.

## Redaction patterns (lines 112 to 126)

```python
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
]
SECRET_KV = re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b(\s*[:=]\s*)([^\s,;]+)")
EMAIL = re.compile(...)
PHONE_PATTERNS = [ ... E.164 ..., ... North American ... ]
```

These are **compiled regular expressions** (`re.compile`), written as **raw strings** (`r"..."`) so
backslashes reach the regex engine untouched. They are the same patterns as the week 3 in-browser
redactor, with one addition:

- `SECRET_KV` catches `api_key=abc123`, `password: hunter2`, and similar. It has three
  **capturing groups** (the parentheses): the key name, the separator, and the value. `(?i)` makes
  it case-insensitive, and `[^\s,;]+` means "one or more characters that are not whitespace, a
  comma, or a semicolon", which is where a value usually ends.
- The phone patterns use **lookbehind** `(?<![\w+])` and **lookahead** `(?![\w])` guards so they
  don't match digits inside longer numbers, dates, or ids.

## `redact` (lines 129 to 142)

```python
for pattern in SECRET_PATTERNS:
    text = pattern.sub("[SECRET]", text)
text = SECRET_KV.sub(lambda m: m.group(1) + m.group(2) + "[SECRET]" if m.group(3) != "[SECRET]" else m.group(0), text)
text = EMAIL.sub("[EMAIL]", text)
for pattern in PHONE_PATTERNS:
    text = pattern.sub("[PHONE]", text)
```

Replaces secrets, then emails, then phone numbers, in that order. The docstring states why:
a key can contain digit runs that look like phone numbers, so secrets must be gone before the
phone patterns run. A test (`test_secret_digits_are_not_mislabeled_as_phone`) checks it.

Line 138 is dense. `SECRET_KV.sub` accepts a **function** as the replacement: for each match `m`,
the **lambda** returns the new text. It keeps the key name and separator (`m.group(1) + m.group(2)`)
and replaces only the value, so the log still says *which* secret was there. The **conditional
expression** at the end (`... if m.group(3) != "[SECRET]" else m.group(0)`) leaves an
already-redacted value alone. That keeps the function **idempotent**: running it twice gives the
same result as once, which matters when a record passes through two services that both redact.

**Reviewing AI-written versions:** check the order, check idempotence (does `[SECRET]` itself
match anything?), and check over-redaction. The tests include dates, prices, and ticket numbers
that must survive unchanged, because a log redacted into mush is useless for debugging.

## `redact_value` (lines 145 to 154)

```python
if isinstance(value, str):
    return redact(value)
if isinstance(value, dict):
    return {k: redact_value(v) for k, v in value.items()}
if isinstance(value, (list, tuple)):
    return type(value)(redact_value(v) for v in value)
return value
```

Applies `redact` to every string inside nested data, by **recursion** (the function calls itself
on each item). A **dict comprehension** rebuilds dictionaries; `type(value)(...)` rebuilds a list
as a list and a tuple as a tuple. Numbers, `None`, and booleans pass through.

It builds new structures instead of changing the input in place, so redacting a record for the log
never alters the data the rest of the program is still using. A test checks the input is unchanged.

## `pseudonymize` (lines 157 to 161)

```python
digest = hmac.new(key, user_id.encode("utf-8"), hashlib.sha256).hexdigest()
return "u_" + digest[:16]
```

Turns a user id (often an email) into a stable, opaque label such as `u_3f9a...`. Same user, same
key, same label, so you can count distinct users and follow one user's calls without storing who
they are.

It uses **HMAC**, a keyed hash, not a plain hash. A plain SHA-256 of an email can be reversed by
anyone with a list of candidate emails: hash each one and look for a match. With HMAC, they also
need the secret key. `.encode("utf-8")` turns the string into bytes, which hashing requires, and
`[:16]` keeps the first 16 hex characters, which is plenty to avoid collisions at this scale.

**Reviewing AI-written versions:** `hashlib.sha256(email).hexdigest()` looks like anonymization and
isn't. Also check where the key comes from: `main` reads `LOG_HMAC_KEY` from the environment and
falls back to an obviously fake development value (line 583).

## `cost_usd` (lines 166 to 179)

The four token counts times their prices, over a million. An unknown model raises `ValueError`
with a message saying exactly what to fix (`{model!r}` in the f-string shows the value with quotes,
so an empty or misspelled id is visible). A silent zero would make the dashboard report a cheaper
system than you have.

This lab's records use their own names for the cache meters (`cache_read_tokens`,
`cache_write_tokens`), and `_usage` (below) maps Claude's names onto them. It prices every write at
the 5-minute rate, which matches how this workflow calls the API.

## The record schema and `validate_record` (lines 184 to 242)

```python
RECORD_FIELDS: dict[str, tuple[type, ...]] = {
    "schema_version": (int,),
    ...
    "error_type": (str, type(None)),
    ...
}
...
if isinstance(value, bool) or not isinstance(value, types):
    problems.append(f"bad type: {name}")
```

`RECORD_FIELDS` is the schema as data: each field name maps to a **tuple of allowed types**.
`(str, type(None))` means "a string or `None`" (`type(None)` is the type of `None`). `isinstance`
accepts a tuple of types, so one check covers both.

`validate_record` returns a **list of problems** rather than raising on the first one, so a nightly
job over a real log can report everything wrong at once. It checks: missing and unexpected fields;
wrong types; an unknown status; negative numbers; previews that aren't fully redacted (by running
`redact` on them and seeing whether anything changes, a neat reuse of idempotence); and an error
record without an error type.

The `isinstance(value, bool)` part (line 225) exists because in Python `True` and `False` are
technically integers (`isinstance(True, int)` is `True`). Without it, `"input_tokens": True` would
pass as a valid count. The test sets exactly that.

## Reading a response (lines 245 to 271)

- `_usage` (lines 245 to 252) pulls the four token counts off the SDK's usage object with
  `getattr(u, name, 0) or 0`, which tolerates a missing attribute or a `None`. It also renames
  Claude's `cache_read_input_tokens` and `cache_creation_input_tokens` to the record's field names.
- `_text` (lines 255 and 256) joins the text of every text block, ignoring other block types.
- `_status` (lines 259 to 264) maps the stop reason to the record's status: `refusal` becomes
  `refused`, `max_tokens` becomes `truncated`, anything else is `ok`.
- `_preview` (lines 267 to 271) returns `None` unless content capture is on. When it is on, it
  **redacts before truncating** to 200 characters. The comment explains why: cutting first could
  split an email into a fragment the pattern no longer recognizes, and the fragment would leak.

## The two logs (lines 274 to 297)

`ListLog` keeps records in memory for tests. `JsonlLog` appends one JSON object per line to a file
(JSONL, "JSON Lines"), which is easy to append to, stream, and load into almost any tool.

- `mkdir(parents=True, exist_ok=True)` (line 289) creates the folder and any missing parents, and
  doesn't fail if it exists.
- `with self.path.open("a", ...)` opens for **append** inside a `with` block, a **context manager**
  that closes the file even if writing fails.
- `json.dumps(record, sort_keys=True)` writes keys in a fixed order, so log lines are easy to diff.
- Both classes have the same `write` method, so `call_step` doesn't care which one it gets. That's
  the same **duck typing** idea as the no-op tracer.

`read_jsonl` (lines 296 and 297) is a **list comprehension** that parses each non-blank line.

## `call_step` (lines 302 to 389)

```python
with tracer.start_as_current_span(f"chat {model}") as span:
    _, span_id = _ids(span, trace_id)
    span.set_attribute("gen_ai.operation.name", "chat")
    ...
    start = clock()
    try:
        response = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                          messages=[{"role": "user", "content": user_text}])
    except Exception as exc:
        record.update(status="error", error_type=type(exc).__name__, ..., cost_usd=0.0, ...)
        span.set_attribute("error.type", type(exc).__name__)
        _mark_error(span, exc)
        log.write(record)
        raise
    ...
    span.set_attribute("gen_ai.usage.input_tokens",
                       usage["input_tokens"] + usage["cache_read_tokens"] + usage["cache_write_tokens"])
```

The heart of the lab: one model call, traced and logged.

- **Keyword-only arguments.** The `*` after `client` (line 304) means every other argument must be
  named. With thirteen parameters, that's the only way a call stays readable and safe from argument
  mix-ups.
- **The span** (line 330). `start_as_current_span` opens a span and makes it the **current** one,
  so any span opened inside it becomes its child. The span name `chat {model}` and the
  `gen_ai.*` attribute names follow the OpenTelemetry GenAI semantic conventions that the docstring
  lists. `_, span_id = _ids(...)` uses `_` for the value it doesn't need.
- **The record is started before the call** (lines 338 to 349) with everything known up front, so
  both the success and the error path finish the same dictionary.
- **Timing uses the injected clock** (lines 350, 361, 368): `clock()` is `time.perf_counter` in
  production and a fake that ticks 0.25 seconds per call in tests, which is why the test can expect
  exactly 250 ms.
- **The error path** (lines 358 to 367) is as important as the happy path. It writes an `error`
  record with zero tokens and zero cost, marks the span as failed (`error.type`, an exception
  event, ERROR status), and then **re-raises** with a bare `raise`. Logging and re-raising means the
  failure is recorded *and* the caller still decides what to do about it. Swallowing the exception
  here would hide outages from every caller.
- **The input token trap** (lines 376 to 379). The semantic conventions define
  `gen_ai.usage.input_tokens` as *all* input, including cached tokens. Claude's `usage.input_tokens`
  counts only the uncached part. So the span adds all three meters. Copying Claude's number straight
  across would make a heavily cached call look tiny on any dashboard built from spans. A test
  checks for 300 + 2000.
- **`record.update(..., **usage)`** (lines 384 to 387) merges keyword arguments into the dictionary;
  `**usage` **unpacks** the four token counts as if each were written out.
- **No content on the span.** Only metadata is set as attributes. The previews go in the log
  record, redacted and only when `capture_content` is on.

**Reviewing AI-written versions:** check that the error path writes a record and re-raises, that the
call passes exactly the four arguments the README specifies (`model`, `max_tokens`, `system`,
`messages`) and nothing more, that no prompt text is set on the span, and that the input token attribute includes cached tokens.

## `parse_category` (lines 392 to 395)

`re.findall(r"[a-z]+", text.lower())` lists the lowercase words in the reply. If the first one is a
known category it's used, otherwise `"other"`. The **conditional expression** handles an empty reply
(`words` is an empty list, which is falsy). Never trust a model's output format blindly: a triage
model asked for one word will sometimes say "Billing." or "Probably billing".

## `run_workflow` (lines 398 to 440)

```python
with tracer.start_as_current_span(WORKFLOW) as root:
    trace_id, _ = _ids(root)
    ...
    try:
        text, rec = call_step(..., step="triage", ...)
        if rec["status"] != "ok":
            return {"trace_id": trace_id, "category": None, "reply": None, "status": rec["status"]}
        category = parse_category(text)
        ...
        reply, rec = call_step(..., step="reply", ...)
    except Exception as exc:
        _mark_error(root, exc)
        raise
```

- `tracer = tracer or get_tracer()` (line 415) uses the given tracer or the default one.
- The **root span** wraps both steps, so the two `chat` spans become its children and share its
  trace id. That id is passed to `call_step` so both log records carry it.
- **Stop early** if triage didn't finish cleanly (lines 427 and 428). A refused or truncated triage
  means the reply step would run on a bad category and spend Opus money for nothing. A test checks
  that only one call is made.
- The reply prompt includes the category and the ticket, built with an f-string.
- The `except` marks the root span as failed too, then re-raises, so a trace view shows the whole
  workflow as failed, not just one step.

## `percentile` (lines 445 to 454)

Nearest rank, as in lesson 6, with two differences from the lab 02 version: it returns `None` for an
empty input (a dashboard row with no data should say "n/a", not crash), and it raises `ValueError`
for a `p` outside (0, 100], so a typo like `percentile(xs, 0.95)` meaning p95 doesn't silently
return the minimum. That check comes after the empty check, so an empty input with a bad `p` still
returns `None`.

## `aggregate` (lines 457 to 503)

```python
for r in records:
    groups.setdefault((r["step"], r["model"]), []).append(r)
    traces.setdefault(r["trace_id"], []).append(r)
...
"error_rate": sum(r["status"] == "error" for r in rs) / n,
...
per_trace_latency = [sum(r["latency_ms"] for r in rs) for rs in traces.values()]
```

Summarizes a log two ways at once: by (step, model), and by trace.

- `dict.setdefault(key, [])` returns the list for that key, creating an empty one the first time.
  It's the standard one-line **group by** in plain Python. The group key is a **tuple**, so the same
  step on two models (say, after a routing change) gets two rows.
- `sorted(groups.items())` sorts by the tuple key, so rows come out by step, then model.
- `sum(r["status"] == "error" for r in rs)` sums booleans: each `True` counts as 1. Dividing by `n`
  gives the rate.
- **Failed calls count toward latency** (the docstring says so, and a test checks a 30-second
  error shows up as the p95). A slow error is still slow for the user; leaving errors out of latency
  makes an outage look like a speedup.
- Input tokens per row add all three meters, matching the span convention.
- **Per-trace latency** is the sum of each trace's steps, and `failed_traces` counts traces with
  any non-`ok` record. `any(...)` is true if at least one item is true.
- `cost_per_trace_usd` is `None` when there are no traces, instead of dividing by zero.

## `render_markdown` (lines 506 to 540)

Builds the dashboard as a list of lines and joins them. The headline section gives traces, failed
traces with a percentage, total cost, cost per trace, and trace latency; the table has one row per
(step, model). Format specs do the presentation: `{x:.1f}` one decimal, `{x:.4f}` four, and
`{x:,.0f}` (in `_fmt_ms`, lines 506 and 507) whole numbers with thousands separators, so
`1234.4` prints as `1,234 ms`. `_fmt_ms` returns `"n/a"` for `None`. The closing line states the
method (nearest-rank, failures included, which price table), which is the honest thing to print
under any chart.

## The command line (lines 545 to 598)

- `_console_tracer` (lines 545 to 555) builds a tracer that prints finished spans to the terminal,
  if `opentelemetry-sdk` is installed, and otherwise falls back with a message.
- `main` uses `argparse` **subcommands**: `dashboard LOG [--out FILE]` renders the dashboard, and
  `run [--log FILE] [--capture-content]` runs the live workflow on the sample tickets.
- The live branch imports `anthropic` only when needed, reads the HMAC key from the environment, and
  catches `anthropic.APIError` per ticket so one failure doesn't stop the batch (`run_workflow`
  already logged it).
- `sys.exit(main())` (line 598) turns the return value into the process's exit code.

## What the tests check

- **Redaction (section 1):** a parametrized list of things that must be caught (keys, bearer tokens,
  key=value secrets, emails, phone formats) and ordinary text that must survive; secret digits not
  becoming `[PHONE]`; idempotence; nested structures redacted without mutating the input; and three
  `xfail` tests that document known gaps (an obfuscated email, a name, a UK national number).
- **Pseudonyms and cost (section 2):** stable, keyed, opaque pseudonyms; Opus and Haiku prices;
  cache reads and writes priced separately; unknown models raise.
- **Records (section 3):** one valid record per step with exactly the schema's fields; exact values
  (latency from the fake clock, cost, shared trace id, distinct span ids, pseudonym); no content by
  default; redacted content when captured; an error logged and re-raised; a refused triage stops the
  workflow; category parsing; the validator catching each kind of problem; a JSONL round trip.
- **Aggregation (section 4):** nearest-rank percentiles; a small hand-checked log (rates, sorting,
  failed calls in latency, trace latency as a sum); the 60-trace sample log; number formatting; the
  CLI.
- **Spans (section 5, needs the SDK):** the span tree (root plus two children), the GenAI attributes
  including the cached input count, real trace and span ids in the records, no content on spans,
  and ERROR status with an exception event on failure.
- **Live:** one ticket through both steps against the real API.

What they don't cover: names, addresses, and other free text the regexes can't recognize (the
README asks you to read live previews to see this), SDK-emitted spans nested under yours (the README
explains the double-counting risk), concurrency, and log rotation or retention.

## Review questions

1. Why does `call_step` set `gen_ai.usage.input_tokens` to the sum of three meters instead of
   Claude's `usage.input_tokens`?

<details>
<summary>Answer</summary>

The semantic conventions define that attribute as all input tokens, cached or not. Claude reports
uncached input, cache reads, and cache writes separately, so its `input_tokens` is only the uncached
part. On a cached call that can be 300 instead of 2,300. Any backend that charts tokens from spans
would understate prompt size, and anything estimating cost from that attribute would be wrong.

</details>

2. An AI assistant "simplifies" `pseudonymize` to `return "u_" + hashlib.sha256(user_id.encode()).hexdigest()[:16]`.
   The output still looks random and is still stable. What's lost?

<details>
<summary>Answer</summary>

Anyone with the log and a list of plausible emails (a customer list, a leaked database) can hash
each email and match the labels, re-identifying users. HMAC requires the secret key to do that.
The tests catch this two ways: a different key must give a different pseudonym, and the result
must not equal a bare SHA-256 of the email.

</details>

3. In the error path, why does `call_step` write a record **and** re-raise, instead of doing just
   one of them?

<details>
<summary>Answer</summary>

Without the record, failures would be invisible on the dashboard, and the error rate would read
zero during an outage. Without the re-raise, the caller would think the call succeeded and carry on
with no response (here, `run_workflow` would try to parse a category from nothing). Logging records
what happened; raising lets the caller decide what to do about it.

</details>

4. `_preview` redacts and then truncates to 200 characters. What could leak if it truncated first?

<details>
<summary>Answer</summary>

A cut at character 200 could land in the middle of an email, a key, or a phone number. The fragment
left behind (`maria.lopez@exa`, say) may no longer match the pattern, so it would pass through
unredacted. Redacting the whole text first means every match is complete when the patterns run.

</details>

5. The dashboard's latency percentiles include failed calls. Give a concrete case where excluding
   them would mislead you.

<details>
<summary>Answer</summary>

During an outage where calls hang for 30 seconds and then fail, excluding errors would drop exactly
those 30-second calls, and the p95 would *improve* while users wait longer than ever. The small-log
test has this case: a 30,000 ms error must show up as the reply step's p95.

</details>
