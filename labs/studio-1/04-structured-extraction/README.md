# Lab 04: Structured extraction you can check

**Goes with:** Studio 1, week 3 (lessons 7 to 9). **Time:** about 60 minutes.

## Goal

Turn a messy business document into action items your code can trust:

1. Define the output once, as Pydantic models (`ActionItem`, `Extraction`).
2. Call Claude with **structured outputs** through `client.messages.parse()`, so the reply is schema-valid.
3. If the reply fails a client-side check, **retry once** with the validation errors fed back.
4. **Verify every evidence quote** against the source text, and flag items whose quote or owner isn't there.

This is the core of the studio project (meeting transcript to action items). The two samples in `samples/` are short,
fictional documents: a vendor email and a support ticket. Both contain real commitments, a request with no clear owner,
and deadlines given as phrases rather than dates.

## Steps

Work in `starter.py`. The tests import from it.

1. **Models.** Fill in `ActionItem` and `Extraction` following the docstrings. Every field is required, nullable
   fields use `X | None`, priority is a `Literal`, extra fields are forbidden, and every field has a description.
   Add the `model_validator` that requires `owner_missing_reason` when `owner` is null.
   Check your work: `python -c "import starter, json; print(json.dumps(starter.Extraction.model_json_schema(), indent=2))"`.
2. **Verification.** Write `normalize` and `verify_evidence`. Normalize whitespace only; match exactly.
3. **Error formatting.** Write `format_errors` (you did this in lesson 7).
4. **The call.** Write `extract`. Use the call shape in the TODO comment. Then:
   - On `pydantic.ValidationError` whose errors include type `json_invalid`, raise `ExtractionFailed` without retrying.
   - On any other `ValidationError`, append `retry_message(err)` to the messages and try once more. A second failure raises `ExtractionFailed`.
   - On success, check `response.stop_reason`: raise `ExtractionFailed` for `refusal` or `max_tokens`.
   - Return an `ExtractionResult` with the parsed extraction, the flags from `verify_evidence`, and the attempt count.
5. Run the offline tests until they pass:

   ```bash
   cd labs && source .venv/bin/activate
   pytest studio-1/04-structured-extraction -q
   ```

6. With a key in `labs/.env`, run the live tests and the script:

   ```bash
   pytest studio-1/04-structured-extraction -q -m live -s
   python studio-1/04-structured-extraction/starter.py
   ```

## How the call works

`client.messages.parse(..., output_format=Extraction)` is the Python SDK's helper for structured outputs. It turns
your Pydantic class into a JSON Schema, sends it as `output_config.format`, and validates the reply against your
original model, returning the result in `response.parsed_output`. Two details matter for this lab:

- The API schema supports a subset of JSON Schema. Constraints such as `min_length` are moved into the field
  description before sending, then checked by the SDK on the way back. Your `model_validator` is checked the same way.
  Those client-side checks are the failures a retry can fix.
- Under constrained decoding, broken JSON shouldn't happen on a completed reply. If parsing fails with `json_invalid`,
  the likely causes are truncation at `max_tokens` or a refusal, and sending the same request again won't help.

(On raw `messages.create()` calls, put the schema in `output_config={"format": {...}}` yourself. The old top-level
`output_format` request parameter is deprecated.)

The fake client in the tests records every `parse()` call, so the tests can check that you retry exactly once, that
the retry includes the errors, and that you never send sampling parameters (they are rejected on the current API).

## Expected cost

Offline tests: free. The live tests make two calls to `claude-opus-5-5` on documents of a few hundred words; at the
pricing listed on the review date ($4 per million input tokens, $20 per million output) that is a few cents in total.
Check the current pricing page before you rely on that number. To compare a cheaper model, call
`extract(client, document, model="claude-haiku-5-5")` and compare the flags.

## What to notice

- **Valid is not verified.** Run the live test with `-s` and read the flags. Any item with a paraphrased quote is
  schema-valid and still unsupported. Your verifier is the only thing that catches it.
- **What the verifier can't see.** In the vendor email, "someone on your side should double-check the delivery address"
  is a real quote, so it passes. Whether it belongs in the list (and with which owner) is a judgment call. Look at how
  the model filled `owner` and `owner_missing_reason` for it. That's the case for a second-model check or human review
  (lesson 9).
- **Dates.** "By end of day Thursday" has no calendar date in the document. A good extraction leaves `due_date` null
  and copies the phrase. Resolving it against the email's date is deterministic code, which the project asks for.
- **Refusal fallbacks.** Anthropic offers a beta server-side fallback that re-runs a declined request on another
  model. It is left out here to keep the call simple; see the structured outputs and refusal docs if you need it.
