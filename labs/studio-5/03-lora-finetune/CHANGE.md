# Change: score whether order ids are grounded in the ticket

## The change

The README describes a failure the loss never shows: the tuned adapter invented order ids for tickets that had none
(one output was `"chango.500"`, built from "500 error" in the ticket). `score_prediction` marks that field wrong,
but it can't tell an invented id from a mistyped one, because it never looks at the ticket. A grounding check can:
an `order_id` must be `null` or appear verbatim in the ticket text.

Ask a coding assistant to add it, without breaking any existing caller:

- A helper `is_grounded(pred, ticket)` returns `True` if `pred["order_id"]` is `None` (or missing), or is a string
  that appears in `ticket`. Anything else (a number, an invented string) is `False`, and it must never raise.
- `score_prediction(text, gold, ticket=None)` gets an optional `ticket`. When it is given, the result has a fourth
  key, `"grounded"`; an output that isn't a valid JSON object is not grounded. When it isn't given, the result is
  exactly the same three keys as today.
- `summarize_scores` adds `"grounded_rate"` only when **every** score has a `"grounded"` key, so a partially
  checked run is never reported as a rate.

Wiring this into `mlx_finetune.py` and the notebook (passing `r["ticket"]`) is a good follow-up, but it is not part of
this change: keep the edit to the scoring functions so it is easy to review.

The work happens in `work.py` (your copy of the solution). The tests import it automatically while it exists.

## Write your prompt

Write your own prompt first, before opening the example. A good prompt for this change:

- states the grounding rule precisely, including `None`, a missing key, and non-string values;
- says the new parameter is optional with a default of `None`, and that the default output must be byte-for-byte
  the same as today (existing tests compare whole dictionaries);
- says what an invalid output gets when a ticket is given;
- says when `summarize_scores` reports the new rate and when it must not;
- limits the scope to `solution`'s scoring functions and asks for docstrings and tests.

## Example prompt

<details><summary>Show the example prompt</summary>

```text
In work.py, add an order-id grounding check to the scoring section.

1. Add is_grounded(pred: dict, ticket: str) -> bool above score_prediction. It returns True if
   pred.get("order_id") is None, or if it is a str that is a substring of ticket. Otherwise False.
   It must not raise for non-string values.

2. Change score_prediction to score_prediction(text, gold, ticket=None). Keep the current logic.
   If ticket is not None, add "grounded" to the result: is_grounded(pred, ticket) for a valid JSON
   object, False for an invalid output. If ticket is None, return exactly the same three keys as now.

3. In summarize_scores, add "grounded_rate" (the mean of "grounded") only if every score has a
   "grounded" key. Otherwise leave the summary exactly as it is now, including the empty case.

Don't change any other function, the strictness of the parser, or mlx_finetune.py and the notebook.
Update the docstrings.

Add tests: the "chango.500" example is not grounded; a copied id and a null id are grounded; an
integer order_id is not grounded and doesn't crash; an invalid output with a ticket gets
grounded False; calls without a ticket return exactly the old dictionaries; and summarize_scores
reports grounded_rate for a fully checked list but not for a mixed one.
```

</details>

## Review the AI's change

Read the diff before running anything. Check:

- **Backward compatibility.** Without `ticket`, `score_prediction` returns exactly `{"valid_json", "fields_correct",
  "exact"}`. An assistant that always adds `"grounded"` breaks the existing tests that compare whole dictionaries.
- **The rule.** `None` and a missing key are grounded; the check uses `isinstance(..., str)` before `in`, so a number
  returns `False` instead of raising `TypeError`.
- **Invalid outputs.** With a ticket, an unparseable output gets `"grounded": False`, not a missing key (which would
  silently drop it from the rate).
- **The rate is all or nothing.** `grounded_rate` appears only when every score was checked. A rate computed over a
  subset, or one that treats a missing key as grounded, would overstate how often the model copies correctly.
- **Strictness unchanged.** The parser still forgives only surrounding whitespace; no fence stripping crept in.
- **Scope.** Only the scoring section changed; `mlx_finetune.py` and the notebook are untouched.

## Check it

From the `labs` folder:

```bash
pytest studio-5/03-lora-finetune/test_change.py -q
```

Then run the full lab to make sure nothing else broke:

```bash
pytest studio-5/03-lora-finetune -q
```

Both should pass. If you then wire the check into `mlx_finetune.py` as a follow-up, rerun a training run and compare
`grounded_rate` with `exact_match`: a model can be grounded and still wrong, but an ungrounded id is always a
fabrication.
