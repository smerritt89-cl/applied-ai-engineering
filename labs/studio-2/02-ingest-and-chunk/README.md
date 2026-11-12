# Lab 02 (Studio 2): Ingest, chunk, and store

**Goes with:** Studio 2, week 2 (lessons 4 to 6). **Time:** about 75 minutes. **Cost:** free; no API key needed.

## Goal

Build the indexing half of a retrieval system, end to end, on a small corpus you can read in five minutes:

1. **Ingest** Markdown, HTML, and plain-text files into clean text plus metadata (source, title, date, and the
   permission groups allowed to see each document).
2. **Deduplicate** exact and near-duplicate documents, keeping the newest version.
3. **Chunk** each document with two strategies: fixed-size windows and a structure-aware Markdown chunker that
   splits at headings, respects a size limit, and overlaps on word boundaries.
4. **Embed and store** the chunks in a small local vector store (pure Python, NumPy if installed, JSON on disk)
   that supports upserts, deletes by document, metadata filters, and **access control applied before ranking**.
5. **Report** chunk statistics for both strategies and look at what a sample query retrieves.

The documents in `docs/` are fictional (an invented retailer, Harbor & Pine Outfitters). `manifest.json` stands in for
the permissions system a real company would have. One file is a near-duplicate copy, one is HR-only, and the HTML page
has navigation, scripts, a footer, and a table, as real intranet pages do.

## Steps

Work in `starter.py`; the tests import from it. The HTML parser, the embedder, `_pack`, and persistence are written
for you. Fill in the functions marked `TODO`, roughly in this order:

1. `normalize_text`, `load_document` (metadata, and **fail closed**: a file with no manifest entry gets no groups).
2. `shingles`, `jaccard`, `dedupe`.
3. `chunk_fixed`, then `split_sections` and `chunk_markdown`. Every chunk records `start` and `end` offsets so that
   `doc.text[start:end] == chunk.text`. That link back to the source is what makes citations possible in week 4.
4. `make_chunks` (copy the document metadata onto every chunk).
5. `LocalVectorStore.upsert`, `delete_document`, `query`. `allowed_groups` is keyword-only with no default, on purpose.
6. `chunk_stats`.

```bash
cd labs && source .venv/bin/activate
pytest studio-2/02-ingest-and-chunk -q
python studio-2/02-ingest-and-chunk/starter.py
```

The script prints chunk statistics for each strategy, the top two hits for a sample query, and writes
`index-fixed.json` and `index-structure.json` next to the script.

Optional: `pip install numpy` to run the NumPy scoring test (skipped otherwise) and speed up search.

## What to notice

- **Fixed windows cut words and sections.** Look at the sample output: a fixed-size chunk can begin "rt the
  print-bridge service", and it may straddle two headings. The structure-aware chunks begin at a heading or a word,
  carry their heading path, and come out smaller on average (about 260 versus 435 characters here). More, smaller
  chunks is a trade-off, not a free win: more vectors to store and search, and less context per hit.
- **The embedder is a stand-in.** `HashingEmbedder` hashes words and word pairs into a vector, so it measures word
  overlap, not meaning. That is enough to test the plumbing offline, and it is also why the sample query ranks the
  "Severity levels" section (which mentions label printing) near the "Label printer failures" section. Swap in a real
  embedding model before judging retrieval quality (see below), and measure with the recall@k tooling from week 1.
- **What gets embedded is not what gets stored.** `embedding_text` prepends the document title and heading path to
  the chunk before embedding, while the stored text stays an exact slice of the source. This is a cheap, deterministic
  cousin of Anthropic's Contextual Retrieval (lesson 5), which uses a model to write a short context per chunk.
- **Dedup is a policy decision.** The two travel policies differ by one line. Which one should win? This lab keeps
  the newest by date; a real team might prefer the canonical source system, or keep both and flag the conflict.
- **Access control lives in the store, not the prompt.** The HR-only salary document must never reach a non-HR
  user's prompt, whatever the query. Filtering after you take the top k is a common bug: it can return too few results
  or, if someone forgets the filter, the wrong ones. Here the filter runs before ranking and cannot be skipped.

## Going further

- **A real embedding model.** Anthropic does not offer an embedding model; its docs point to Voyage AI
  (`pip install voyageai`, with `input_type="document"` for chunks and `"query"` for queries). Open-weight models via
  `sentence-transformers` run locally. Write a class with the same `embed(texts)` method and a `dim` attribute.
- **Chroma.** `pip install chromadb`, then add the chunks to a collection with your vectors, `ids`, and metadata, and
  query with a `where` filter on the groups field. Compare its results with `LocalVectorStore` on the same vectors;
  they should match for exact search. Read the Chroma docs on metadata filtering and deletes first.
- **Code fences.** `split_sections` treats a line such as `# install deps` inside a fenced code block as a heading.
  Add a test with a fenced block, then fix the bug.
