# Lab 02 (Studio 5): Build a supervised fine-tuning dataset

**Goes with:** Studio 5, week 2 (lessons 4 to 6). **Time:** about 90 minutes.

## Goal

Turn labeled examples into a training set you would be willing to fine-tune on, and a test set you would be willing
to report a number from. The task is the one from Studio 1: extract action items (task, owner, deadline, priority,
and a verbatim evidence quote) from business documents. The output is in the chat format that week 3's LoRA
fine-tuning tools accept.

You will:

1. **Validate every gold label**: schema, verbatim evidence, owner present in the source, and no model-drafted label
   sneaking in as gold.
2. **Remove exact and near-duplicate documents** with word shingles and Jaccard similarity.
3. **Split** into train, validation, and test, stratified by document kind and keeping email and ticket threads
   together, so related documents never straddle a split.
4. **Check for leakage** across splits, write train and validation as chat JSONL, and **freeze** the test set with a
   fingerprint.
5. **Validate the JSONL** the way a training job would (roles, empty turns, length), plus the checks a job won't do for
   you (schema-valid answers, duplicates, answers leaked into the prompt).
6. Optionally, **draft labels for new documents with Claude**. Drafts are marked `needs_review` and the pipeline
   refuses to train on them until a person has checked them.

Everything except step 6 runs offline.

## Files

| File | What it is |
|---|---|
| `data/sources.jsonl` | 50 fictional documents (emails, support tickets, meeting notes, chat messages) with gold labels. 44 are clean. Six are planted problems: one exact duplicate, two near-duplicates, and three records with bad labels (a paraphrased quote, a null owner with no reason, and an owner who is not in the text). |
| `data/unlabeled.jsonl` | Four new documents with no labels, for the optional drafting step. |
| `starter.py` | Your file. The label schema, the build pipeline, and the writer are provided; the functions marked `TODO` are yours. The tests import from it. |
| `solution.py` | A reference implementation. Try first. |

All people, companies, and email addresses are invented. Domains use the reserved `.example` suffix.

Each record looks like this (shortened):

```json
{"id": "m01", "kind": "meeting", "thread": "th-m01", "text": "Weekly product sync, ...",
 "label": {"items": [{"task": "Send the revised budget to finance", "owner": "Priya", "owner_missing_reason": null,
   "due_date": null, "due_phrase": "by November 20", "priority": "medium",
   "evidence": "I'll send the revised budget to finance by November 20."}]}}
```

Eight of the 44 clean documents have no action items at all. Keep them: a model that never sees an empty answer
learns to invent items.

## Steps

Work in `starter.py`, in this order. Run the tests after each step:

```bash
cd labs && source .venv/bin/activate
pytest studio-5/02-sft-dataset -q
```

1. **`normalize_ws` and `validate_record`.** Exact substring matching after whitespace normalization, as in Studio 1.
   Report schema errors with their location (`schema: items.0.priority: ...`) and stop there, because evidence checks
   on a malformed label are meaningless.
2. **`normalize_for_dedup`, `shingles`, `jaccard`, `dedupe`.** Five-word shingles, threshold 0.7. Before you write
   `dedupe`, print the Jaccard similarity of every pair of records and look at the distribution: the planted
   duplicates sit far above everything else in this data. In real data the gap is rarely that clean, which is why
   lesson 6 tells you to read a sample of the pairs near your threshold.
3. **`stratified_group_split`.** Follow the algorithm in the docstring exactly so the tests can check the result. The
   point is the two constraints: whole groups only, and each kind represented in every split.
4. **`check_split_leakage`.** Compare every pair of records in different splits. With 44 records that's cheap; for
   millions you'd use MinHash and locality-sensitive hashing (lesson 6, GoDeeper).
5. **`to_chat_example`, `validate_chat_lines`, `fingerprint`.** The chat format is the `messages` list that OpenAI's
   fine-tuning API and Hugging Face TRL's `SFTTrainer` both accept. Serialize the label with `sort_keys=True` so
   duplicates are detectable.
6. Run the whole build:

   ```bash
   python studio-5/02-sft-dataset/starter.py
   ```

   It prints what was quarantined and dropped, the size and mix of each split, and the test fingerprint, then writes
   `out/train.jsonl`, `out/val.jsonl`, `out/test.jsonl`, and `out/manifest.json`. Commit the manifest, not the data,
   when you work with real customer data.

## Optional live step: model-drafted labels

`draft_label` asks Claude (structured outputs, the same call shape as Studio 1 lab 04) to label a new document, then
runs your validator on the draft. With a key in `labs/.env`:

```bash
pytest studio-5/02-sft-dataset -q -m live -s
```

The test drafts labels for the four documents in `data/unlabeled.jsonl` and prints them with any flags. **Every draft
is marked `"label_status": "needs_review"`, and `validate_record` rejects it as training data until a person changes
that to `"reviewed"`.** Read each draft against its document. Look for the cases this course keeps returning to: a
suggestion ("we should probably revisit the pricing page") recorded as a commitment, a group request ("can everyone
else add their names") given a single owner, and a weekday deadline turned into an invented calendar date. If you
accept a draft, you are the labeler, and its errors become your model's errors.

**Terms of service matter here.** Using one provider's model outputs to train another model is restricted by some
providers' terms (lesson 5 compares them). For this lab the drafts are reviewed and corrected by you and used to train a
small model on your own extraction task; read your provider's current terms before you do the same at work, and ask
your legal team rather than relying on a course.

**Expected cost:** four calls to `claude-opus-5-5` on documents of under 100 words each, a few cents at the pricing
listed on the review date ($4 per million input tokens, $20 per million output). Check the current pricing page.

## What to notice

- **Duplicates distort two things.** In training they overweight whatever they repeat. Across splits they inflate
  your test score, because the model has seen the answer. The forwarded ticket `t07-fwd` lives in a different thread
  from `t07`, so only content-based near-duplicate detection catches it; a group-aware split alone would not.
- **The test set is small.** Eight test documents can only catch large failures (Studio 3, week 1 has the margin of
  error math). For the week 4 benchmark you'll want more labeled examples than this lab ships; the drafting step plus
  human review is one honest way to get them.
- **Quarantine, don't delete.** The three bad labels are reported, not silently dropped. Fix them (or relabel the
  documents) and they rejoin the pipeline on the next build. The test fingerprint will change if a fix touches the
  test split, which is exactly the signal you want.
