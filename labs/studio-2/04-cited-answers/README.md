# Lab 04 (Studio 2): Cited answers you can check

**Goes with:** Studio 2, week 4 (lessons 10 to 12). **Time:** about 60 minutes.

## Goal

Generate an answer grounded in retrieved passages, then prove, in code, that its citations are real:

1. Send each retrieved passage to Claude as a **`search_result` block** with citations enabled, sources first and
   the question last.
2. Parse the response into **claims**, each with the citations the API attached.
3. Parse a **prompt-based** citation format too (`[passage-id: "exact quote"]`), the kind you'd ask any provider for.
4. **Verify offline**: every citation names a passage you actually sent, any index points at that same passage, and
   every quoted span appears verbatim in it. Flag substantive text that carries no citation, and recognize abstention.

The passages in `passages.json` are a short, fictional travel and expense policy. One of them is an archived FAQ
that contradicts the current policy. That's deliberate.

## Steps

Work in `starter.py`. The tests import from it.

1. **The request.** Write `build_search_results` and `build_messages`. The passage id goes in `source`, so every
   citation names the passage it came from. Citations must be enabled on all search results or none.
2. **Parsing.** Write `parse_claude_response`. A cited answer arrives as several `text` blocks; some carry a
   `citations` list. Skip non-text blocks (thinking can't be turned off on Claude Opus 5.5, so a `thinking` block can appear first).
   Use the `_get` helper so the same code reads SDK objects, logged JSON, and the fixtures.
3. **Provider-agnostic parsing.** Write `parse_marked_answer` for the bracket format in `fixtures/marked_answer.txt`.
4. **Verification.** Write `normalize` and `verify_answer`, following the docstring exactly.
5. **The call.** Write `answer_with_citations` with `client.messages.create(...)`.
6. Run the offline tests until they pass:

   ```bash
   cd labs && source .venv/bin/activate
   pytest studio-2/04-cited-answers -q
   ```

7. With a key in `labs/.env`, run the live tests and the script:

   ```bash
   pytest studio-2/04-cited-answers -q -m live -s
   python studio-2/04-cited-answers/starter.py
   ```

## How the request works

A `search_result` block has a `source` (any stable string: a URL or an id such as `travel-002`), a `title`, and
`content` (a list of text blocks). With `"citations": {"enabled": true}`, text in the reply that draws on a result
carries `search_result_location` citations with `source`, `title`, `cited_text`, `search_result_index`, and the
`start_block_index` / `end_block_index` of the cited text blocks. The text block is the smallest unit Claude can cite,
so if you want sentence-level citations, split each passage into one text block per sentence.

Three facts from the citations docs shape this lab (read on the review date):

- **Citations and structured outputs don't mix.** Sending `output_config.format` with citations enabled returns a
  400, so this lab uses `messages.create`, not `messages.parse`.
- **`cited_text` is free.** It doesn't count toward output tokens, which makes API citations cheaper than asking the
  model to write its quotes out.
- **API citations are guaranteed to point at documents you provided.** So why verify them? Because the verifier
  runs on anything: answers replayed from logs, answers from other providers in the bracket format, answers that
  passed through code you or a teammate wrote. And because the guarantee is about *where the quote came from*, not
  whether the quote supports the sentence it's attached to.

## Expected cost

Offline tests: free. Each live call sends about 1,500 input tokens and gets back about 100 to 300 output tokens on
`claude-opus-5-5`. At the prices listed on the review date ($4 per million input tokens, $20 per million output),
both live tests together cost about 2 cents. Check the current pricing page before you rely on that number. To try
the cheapest tier, pass `model="claude-haiku-5-5"` and compare the citations.

## What to notice

- **Valid citations, wrong answer.** In `marked_answer.txt`, the first line quotes the archived 2023 FAQ word for
  word, and your verifier passes it. The current policy says something else. Mechanical checks prove the quote
  exists; they can't tell you the source is stale. That's a data problem (lesson 11): drop or demote outdated
  documents at ingestion, and carry dates as metadata so the prompt can prefer the newer one.
- **Uncited text is a warning, not an error.** Connective phrases ("Usually not.") don't need citations. A sentence
  with a number in it ("capped at 100 US dollars") does. The `is_substantive` rule is a crude heuristic; in the
  project you'll measure how often it flags real problems.
- **Support is a separate question.** A citation can point at a real passage that doesn't actually support the
  claim. Checking that needs a model or a person (a narrow, per-claim judge you calibrate against your own labels),
  which is Studio 3's territory.
- **Refusal fallbacks.** Anthropic offers a beta server-side fallback that re-runs a declined request on another
  model. It's left out here to keep the call simple; see the refusals docs if you need it.
