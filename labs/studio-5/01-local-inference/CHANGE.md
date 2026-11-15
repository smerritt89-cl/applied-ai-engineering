# Change: keep the thinking text and the first-chunk time

## The change

`consume_ollama_stream` currently throws away two things a benchmark needs when the model is a reasoning model.
Thinking chunks (`message.thinking`) are ignored entirely, and the arrival time of the very first chunk is not
recorded, so you can't tell whether a slow TTFT was the model thinking, the model loading, or the network.

Ask a coding assistant to extend it:

- `StreamResult` gets two new fields: `thinking` (the concatenated `message.thinking` text, `""` if there was none)
  and `first_chunk_s` (the arrival time of the first non-blank chunk of any kind, `None` if there were none).
- `consume_ollama_stream` fills them in. Everything it does today stays the same: TTFT is still the first chunk
  with visible **content**, the answer text still contains only content, and the error and truncation checks still
  raise.

On the fixture stream, `first_chunk_s` should be 0.412, `ttft_s` still 0.731, and `thinking` should be
`"The customer wants a refund."`.

The work happens in `work.py` (your copy of the solution). The tests import it automatically while it exists.

## Write your prompt

Write your own prompt first, before opening the example. A good prompt for this change:

- names the function and the dataclass to change, and the exact new field names, types, and defaults;
- defines `first_chunk_s` precisely (non-blank, any kind of chunk) so it isn't confused with TTFT;
- says what must **not** change: the TTFT definition, the answer text, the error and truncation behavior, and the
  existing fields of `StreamResult`;
- points out that new dataclass fields after `final` need defaults (or the class won't even load);
- asks for tests, including one with no thinking chunks and one where a blank line comes first;
- asks for the docstring to be updated.

## Example prompt

<details><summary>Show the example prompt</summary>

```text
In work.py, extend consume_ollama_stream and its StreamResult dataclass.

Add two fields to StreamResult after `final`, both with defaults so existing code that builds
StreamResult(text=..., ttft_s=...) keeps working:
- thinking: str = ""  (the concatenation of every chunk's message.thinking, in order)
- first_chunk_s: float | None = None  (the arrival time of the first non-blank line that parses
  as a chunk, whatever it contains)

In consume_ollama_stream, fill both in. Read thinking the same defensive way content is read
(message may be missing, thinking may be missing or None). Set first_chunk_s once, after the
blank-line skip and the error check.

Do not change: how TTFT is defined (first chunk with non-empty content), the answer text (content
only, never thinking), the RuntimeError for error chunks, the ValueError for a missing done chunk,
or any other function. Update the docstring to describe the two new fields.

Add tests: on fixtures/ollama_chat_stream.json, thinking == "The customer wants a refund.",
first_chunk_s == 0.412 and ttft_s is still 0.731; a stream with a blank line first does not use
the blank line's time; a stream with no thinking chunks gives thinking == "".
```

</details>

## Review the AI's change

Read the diff before running anything. Check:

- **Scope.** Only `StreamResult` and `consume_ollama_stream` changed (plus tests). No edits to `parse_ollama_final`,
  the adapters, or the CLI "while it was in there".
- **TTFT is untouched.** It is still set from the first chunk with non-empty content. A common slip is to set TTFT
  from the first thinking chunk, which silently changes what every benchmark reports.
- **The answer text has no thinking in it.** Thinking goes in its own list and its own field.
- **`first_chunk_s` is set once and after the blank-line skip.** Setting it before the skip would record a blank
  line's time; setting it on every chunk would record the last one.
- **Defaults.** Both new fields have defaults, so `StreamResult(text="x", ttft_s=None)` still works. Without them
  Python raises a `TypeError` when the class is defined, because a field without a default can't follow one with a
  default.
- **Docstring and tests.** The docstring describes both fields, and there are tests for the fixture, a blank first
  line, and a stream without thinking.

## Check it

From the `labs` folder:

```bash
pytest studio-5/01-local-inference/test_change.py -q
```

Then run the full lab to make sure nothing else broke:

```bash
pytest studio-5/01-local-inference -q
```

Both should pass. If `test_change.py` passes but the main tests fail, the change broke existing behavior; read the
failing test's message, then tell the assistant exactly which behavior must be restored.
