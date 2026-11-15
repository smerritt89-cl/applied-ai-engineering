# Walkthrough: ingest, chunk, and store

## What this code does

This is the indexing half of a retrieval system: everything that happens before anyone asks a question. It reads a folder of Markdown, HTML, and text files, turns each into clean text with metadata (where it came from, its title and date, and who may see it), removes duplicates, cuts each document into chunks, turns each chunk into a vector, and stores the vectors in a small searchable index.

The file is laid out as a pipeline, in the same order the data flows: parsing and cleaning, deduplication, chunking, embeddings, the vector store, and statistics. Each stage takes plain Python objects from the one before, so you can test any stage on its own.

Two promises run through the whole design. First, every chunk records `start` and `end` offsets so that `doc.text[start:end] == chunk.text`, which is what makes exact citations possible later in the studio. Second, access control is enforced inside the store's search, before ranking, and the caller cannot forget to pass it.

## How to read this lab

Open `work.py` beside this page. It starts as an exact copy of `solution.py`, so the line numbers below match it until you edit it. Run the tests from VS Code's **Testing** panel (the flask icon); they should all pass against `work.py`. One test needs NumPy and is skipped without it.

Read top to bottom. Spend the most time on `load_document`, `dedupe`, `split_sections`, `_pack`, and `LocalVectorStore.query`: those are where the design decisions live.

## `Document` and `Chunk` (lines 30 to 41)

```python
@dataclass
class Document:
    doc_id: str
    text: str
    metadata: dict = field(default_factory=dict)
```

`@dataclass` is a **decorator** that generates a constructor, a readable printout, and equality comparison from the listed fields. These two classes are just labeled containers: an id, the text, and a metadata dict.

`field(default_factory=dict)` gives every new object its own empty dict. A plain `= {}` default would be shared by every instance in an ordinary class, a classic Python bug; dataclasses refuse it, which is why this form exists.

## Turning HTML into text: `_HTMLToText` and `html_to_text` (lines 47 to 104)

```python
class _HTMLToText(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "head", "noscript"}
    ...
    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1
            return
```

Python's standard library includes `HTMLParser`, which reads HTML and calls a method for every opening tag, closing tag, and piece of text. This class **inherits** from it (the parent class goes in parentheses) and overrides those three methods. The leading underscore in `_HTMLToText` is a convention meaning "internal, not part of this module's public interface".

What it keeps and drops is the point:

- **Boilerplate is skipped.** Anything inside `script`, `style`, `nav`, `footer`, `head`, or `noscript` is ignored. `skip_depth` is a counter rather than a true/false flag, so a skipped tag nested inside another skipped tag doesn't end the skipping too early. `max(0, ...)` on line 75 keeps a stray closing tag from driving it negative. The test checks that `window.analytics`, CSS, "Cookie settings", and the nav link "Home" never reach the text.
- **Headings become Markdown headings.** An `h2` turns into `## ` (line 65), so the HTML page can be chunked by the same heading-aware code as the Markdown files. This is a small, deliberate design choice: convert everything to one format early, and write the hard logic once.
- **Tables survive as rows.** Cell text is collected per cell and per row, then written as `| a | b | c |` (line 83). Dropping tables, or flattening them into one run-on line, is a common ingestion bug, and tables often hold exactly the facts people ask about (here, return windows).

`super().__init__(convert_charrefs=True)` calls the parent class's constructor and asks it to turn entities such as `&amp;` into `&`.

`html_to_text` (lines 97 to 104) runs the parser, joins the collected pieces, collapses runs of spaces inside each line with `" ".join(line.split())` (`split()` with no argument splits on any whitespace and drops empties), and then normalizes. It calls `normalize_text`, which is defined further down; that works because Python looks the name up when the function runs, not when it is defined.

## `normalize_text` (lines 107 to 113)

```python
text = unicodedata.normalize("NFKC", text)
text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00ad", "")  # the file has the literal character
lines = [line.rstrip() for line in text.split("\n")]
text = re.sub(r"\n{3,}", "\n\n", text)
return text.strip() + "\n"
```

This cleans text without changing its words, in a fixed order:

- **NFKC** is a Unicode normalization that folds look-alike characters into standard ones. The "fi" ligature that PDF extractors often produce becomes the two letters `f` and `i`, so a search for "file" can match.
- **Line endings** from Windows (`\r\n`) and old Macs (`\r`) all become `\n`. The order matters: replacing `\r` first would turn `\r\n` into two newlines.
- **Soft hyphens** (Unicode U+00AD, invisible in most editors) are removed. Line 109 contains the actual character between the quotes, which is why it looks like an empty string; an AI "cleaning up" that line might delete what looks like a no-op. The starter's docstring names it as `­`, which is the safer way to write it.
- **Trailing spaces** are stripped from each line, and three or more newlines collapse to two (a **regular expression**: `\n{3,}` means "three or more newlines").
- The result always ends with exactly one newline.

Why it matters: content hashes (next section) are computed on this cleaned text, so two copies of a file that differ only in line endings or trailing spaces get the same hash and are recognized as exact duplicates.

## Hashing and loading: `content_hash`, `load_manifest`, `load_document`, `load_corpus` (lines 116 to 154)

```python
entry = manifest.get(path.name, {})
metadata = {
    "source": path.name,
    "title": entry.get("title", path.stem),
    "date": entry.get("date"),
    "groups": sorted(entry.get("groups", [])),  # no manifest entry -> visible to nobody
    ...
}
return Document(doc_id=metadata["content_hash"][:12], text=text, metadata=metadata)
```

`content_hash` returns a SHA-256 fingerprint of the text as 64 hex characters. `load_manifest` reads `manifest.json` (the stand-in for a company's permissions system) or returns an empty dict if there is none.

`load_document` picks a parser by file extension, and raises `ValueError` for anything else rather than guessing. Then it builds the metadata with `dict.get`, which returns a fallback instead of raising `KeyError` when a key is missing:

- **Fail closed.** A file with no manifest entry gets `groups == []`, which means nobody can retrieve it. The opposite default (visible to everyone) is the dangerous one: a file someone drops into the folder by mistake would become searchable by all staff. This is one of the most important lines in the lab, and one an AI-written version might get wrong by defaulting to `["all-staff"]` "so search works".
- **Source is the file name, not the full path.** Absolute paths leak details about the machine and break when the index moves. The test checks this.
- `path.stem` is the file name without its extension (`stray-notes` from `stray-notes.md`), used as the title fallback.

`doc_id` is the first 12 characters of the content hash. That gives a stable id that depends only on the text. It has a consequence worth knowing when you review changes: if a document is edited, its id changes, so its new chunks get new ids and do not replace the old ones. The caller has to delete the old version with `delete_document(old_id)`.

`load_corpus` lists the folder, keeps supported extensions, and **sorts** the paths. Sorting makes the order (and everything downstream) the same on every machine; `iterdir()` alone returns files in whatever order the file system chooses.

## Near-duplicate detection: `shingles` and `jaccard` (lines 160 to 170)

```python
words = re.findall(r"\w+", text.lower())
...
return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}
```

A **shingle** is a run of n consecutive words. "A b c d e f" with n = 5 has two: `(a, b, c, d, e)` and `(b, c, d, e, f)`. The curly braces with `for` inside are a **set comprehension**, so repeated shingles count once. Tuples are used because sets can hold tuples but not lists.

`jaccard` is the overlap between two sets: the size of the intersection (`&`) divided by the size of the union (`|`). Two documents that differ by one line share almost all their 5-word shingles and score close to 1. Two empty sets are defined as identical (1.0) to avoid dividing by zero. Texts shorter than n words become a single short shingle rather than nothing, so they can still be compared.

## `dedupe` (lines 173 to 199)

```python
docs = sorted(docs, key=lambda d: d.metadata.get("date") or "", reverse=True)
...
if h in seen_hashes:
    dropped.append({... "reason": "exact"})
    continue
...
if jaccard(sh, other_sh) >= threshold:
```

The policy is stated in the comment on line 174: when two documents are duplicates, keep the newest. The function implements it by sorting newest first, then walking through and keeping each document only if it doesn't match anything already kept. Whatever is kept first wins, so sorting is the whole policy.

`sorted(..., key=lambda d: ..., reverse=True)` sorts by date using a **lambda** (a small unnamed function). Dates are ISO strings like `2026-10-15`, which sort correctly as text. `... or ""` turns a missing date into the empty string, which sorts lowest, so undated documents end up last and lose ties. That is a choice, not an accident; a different team might prefer to flag undated duplicates for a person to resolve.

Each document goes through two checks, cheapest first. An exact match on the content hash is a dictionary lookup. Only if that misses does the code compute shingles and compare against every kept document. `continue` skips to the next document as soon as it is dropped. The `dropped` list records what was removed and why, so the decision can be audited; silently discarding documents is how a knowledge base loses content without anyone noticing.

Comparing every pair is fine for six files. For thousands of documents, teams use techniques such as MinHash to avoid it, but the idea (shingles plus Jaccard) is the same.

## Headings and trimming: `HEADING_RE` and `_trim` (lines 204 to 212)

`HEADING_RE` is a compiled regular expression for a Markdown heading line: one to six `#` characters, whitespace, then the title, ignoring trailing spaces and optional closing `#`s. `re.MULTILINE` makes `^` and `$` match at the start and end of every line, not just the whole text. The two parenthesized groups capture the hashes (so `len(group(1))` is the level) and the title.

`_trim` moves `start` forward past whitespace and `end` back past whitespace and returns the new pair. Chunkers trim offsets rather than calling `.strip()` on the text, because stripping the text would break the `text[start:end] == chunk.text` promise.

## `chunk_fixed` (lines 215 to 228)

```python
step = size - overlap
pos = 0
while pos < len(text):
    start, end = _trim(text, pos, min(pos + size, len(text)))
    ...
    if pos + size >= len(text):
        break
    pos += step
```

The simplest strategy: windows of `size` characters, each starting `size - overlap` after the last. For 250 characters with size 100 and overlap 20, windows start at 0, 80, and 160, and the last one reaches the end. The `break` stops once a window has covered the end, so there is no tiny leftover window.

The guard on line 216 rejects `overlap >= size`: the step would be zero or negative and the loop would never finish. Validating parameters that could cause an infinite loop is a good habit to look for in review.

This strategy ignores words and headings, which is why the README shows a chunk starting "rt the print-bridge service". The tests prove it does this on the real corpus.

## `split_sections` (lines 231 to 245)

```python
for i, m in enumerate(matches):
    level = len(m.group(1))
    path = [p for p in path if p[0] < level] + [(level, m.group(2).strip())]
    end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
    if not text[m.end() : end].strip():
        continue
    sections.append({"headings": [t for _, t in path], "start": m.start(), "end": end})
```

This finds every heading and turns the text into sections, each from one heading to the next, with its **heading path**: the chain of parent headings above it.

The path logic is the clever line. `path` holds `(level, title)` pairs. When a new heading arrives, keep only the entries with a smaller level (its ancestors), then add the new one. Walking the test's example:

- `# Guide` gives `[Guide]`.
- `## Time off` gives `[Guide, Time off]`.
- `### Vacation` gives `[Guide, Time off, Vacation]`.
- `### Sick days` drops `Vacation` (same level) and gives `[Guide, Time off, Sick days]`.
- `## Equipment` drops both level-3 and level-2 entries and gives `[Guide, Equipment]`.

A heading with no body of its own, like `## Time off`, produces no section (the `continue` on line 243) but stays in its children's paths, so nothing is lost. Text before the first heading becomes a section with an empty path (lines 234 to 236).

`enumerate` gives the index along with each match, which the code needs to find where the next heading starts.

The known weakness, which the README invites you to fix: a line such as `# install deps` inside a fenced code block matches the heading pattern and splits the section in the wrong place. That is this lab's `CHANGE.md` task.

## Splitting long sections: `_best_break` and `_pack` (lines 248 to 278)

```python
for sep in ("\n\n", "\n", ". ", " "):
    idx = text.rfind(sep, pos + min_len, limit)
    ...
nxt = max(cut - overlap, pos + 1)
while nxt < cut and not text[nxt - 1].isspace():  # start the overlap on a word boundary
    nxt += 1
```

These are provided in the starter, but they are worth reading because they decide where long sections are cut.

`_pack` returns a section whole if it fits in `max_chars`. Otherwise it walks forward. For each piece it asks `_best_break` for the best place to end, trying separators from strongest to weakest: a blank line (paragraph), a newline, a sentence end, then any space. `rfind` searches from the right, so the cut is as late as possible within the limit. The search starts `min_len` (a quarter of `max_chars`) past the current position, so a paragraph break near the start can't produce a uselessly tiny chunk. Only if no separator exists does it cut at the hard limit.

Then it steps back by `overlap` characters for the next piece, so a sentence near a boundary appears in both chunks. Two details prevent bugs:

- `max(cut - overlap, pos + 1)` guarantees the next start is past the current one, so the loop always makes progress even if the overlap is large.
- The `while` loops move the start forward to the beginning of a word and past whitespace, so overlapping chunks don't begin mid-word. The test checks this on every consecutive pair.

## `chunk_markdown`, `STRATEGIES`, and `make_chunks` (lines 281 to 313)

```python
for sec in split_sections(text):
    for s, e in _pack(text, sec["start"], sec["end"], max_chars, overlap):
        out.append({"start": s, "end": e, "text": text[s:e], "headings": list(sec["headings"])})
```

`chunk_markdown` is the structure-aware strategy: split by headings first, then pack each section. Because packing happens within one section, no chunk can cross a heading. `list(sec["headings"])` makes a copy, so chunks from the same section don't share one list that a later edit could change for all of them.

`STRATEGIES` (lines 291 to 294) maps a strategy name to a `lambda` with its settings filled in (500 characters, 50 overlap). Adding a strategy means adding one entry.

`make_chunks` runs a strategy over a document and wraps each piece in a `Chunk`. `meta = dict(doc.metadata)` copies the document's metadata before `update` adds the chunk's own fields. Without the copy, every chunk would write into the same dictionary as the document, and the document would end up with the last chunk's `strategy` and offsets. The test checks that the document's metadata is untouched. This copy-before-mutate step is easy for AI-written code to skip.

The chunk id `doc_id:strategy:index` is unique and predictable, which is what lets `upsert` replace a re-ingested document instead of duplicating it.

## `embedding_text` (lines 316 to 319)

```python
header = " > ".join([chunk.metadata.get("title", "")] + chunk.metadata.get("headings", []))
return f"{header}\n{chunk.text}" if header.strip() else chunk.text
```

What gets embedded is not quite what gets stored. The embedded text starts with a header such as `Warehouse Systems Incident Runbook > Label printer failures`, then the chunk. A chunk that says "restart the service" now carries which document and section it came from, which helps a query about label printers find it. The stored text stays an exact slice of the source, so citations still work. The `... if ... else ...` is a **conditional expression**.

## `HashingEmbedder` (lines 325 to 350)

```python
features = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
for feat in features:
    i, sign = self._index(feat)
    vec[i] += sign
```

A deterministic stand-in for a real embedding model. Each word and each adjacent word pair (`zip(words, words[1:])` pairs every word with the next) is hashed with BLAKE2b to a bucket and a sign of plus or minus 1, then the vector is scaled to length 1. The random-looking sign means collisions between unrelated features tend to cancel instead of piling up.

It measures word overlap, not meaning, as the docstring and README say. It exists so the plumbing can be tested offline. Anything that consumes it only needs an `embed(texts)` method and a `dim` attribute, which is what makes a real model a drop-in replacement.

## The vector store: `_matches` and `LocalVectorStore` (lines 356 to 413)

```python
def query(self, vector, k, *, allowed_groups, where=None):
    if allowed_groups is None:
        raise ValueError("allowed_groups is required: pass the caller's groups explicitly")
    allowed = set(allowed_groups)
    eligible = [
        (cid, r)
        for cid, r in self.records.items()
        if allowed & set(r["metadata"].get("groups", [])) and _matches(r["metadata"], where)
    ]
    ...
    top = heapq.nlargest(k, range(len(eligible)), key=lambda i: scores[i])
```

The store keeps a dict from chunk id to `{"text", "metadata", "vector"}`.

- **`upsert`** (lines 372 to 378) means "insert or update". Writing `self.records[chunk_id] = ...` replaces any existing record with that id, so re-ingesting the same document replaces its chunks instead of duplicating them. It rejects mismatched list lengths and wrong vector dimensions up front; a 384-number vector in a 512-number store would otherwise fail much later, or silently produce wrong scores.
- **`delete_document`** (lines 380 to 384) first collects the ids to delete, then deletes them. Deleting from a dict while looping over it raises `RuntimeError`, which is why the two steps are separate.
- **`query`** (lines 386 to 402) is where access control lives. The bare `*` in the signature makes everything after it **keyword-only**: callers must write `allowed_groups=...` by name. Because it has no default, forgetting it is a `TypeError`, and passing `None` is a `ValueError`. There is no way to call it that quietly means "everyone". An empty set means "no groups" and returns nothing.

The filter runs **before** ranking. Only chunks whose groups overlap the caller's groups (`allowed & set(...)` is a set intersection, and a non-empty set counts as true) and that match the optional `where` filter are scored. Filtering after taking the top k is a common bug: if the top 5 happen to be HR-only, a non-HR user gets zero results, and if someone forgets the post-filter, they get HR data. `_matches` (lines 356 to 359) checks exact equality for every key in `where`; `all(...)` of an empty filter is true.

`heapq.nlargest(k, range(len(eligible)), key=...)` returns the indexes of the k highest scores without sorting everything. The test checks that results come back highest first.

`save` and `load` (lines 404 to 413) write and read the whole store as JSON. `load` is a **classmethod**: it's called on the class (`LocalVectorStore.load(path)`) and returns a new instance.

## `_scores` (lines 416 to 421)

```python
try:
    import numpy as np
except ImportError:
    return [sum(a * b for a, b in zip(row, vector)) for row in matrix]
return (np.asarray(matrix, dtype=float) @ np.asarray(vector, dtype=float)).tolist()
```

Scores are dot products. Because every stored vector and every query vector from `HashingEmbedder` has length 1, the dot product equals cosine similarity. NumPy is used if installed (`@` is matrix multiplication, computing every row's dot product at once); otherwise a pure Python fallback gives the same numbers. `try`/`except ImportError` is the standard pattern for an optional dependency.

The store itself does not normalize vectors. If you swap in a model that returns vectors of varying length, scores become raw dot products, and longer vectors win regardless of meaning. That is worth checking whenever a different embedder is plugged in.

## `chunk_stats`, `build_index`, and `main` (lines 427 to 466)

`chunk_stats` reports count, min, max, mean, median, and two warning counts: chunks over the size limit and chunks under 100 characters. `sum(n > max_chars for n in lengths)` counts how many comparisons are true, because Python treats `True` as 1. An empty list returns zeros instead of crashing on `min([])`.

`build_index` chunks every document, embeds the `embedding_text` of every chunk in one call, and upserts them. The nested comprehension `[c for d in docs for c in make_chunks(d, strategy)]` reads left to right like two nested loops.

`main` deduplicates, then for each strategy builds an index, prints stats and the top two hits for a sample query as an `ops` and `all-staff` user, and saves the index as JSON.

## What the tests check

- **Parsing and cleaning**: normalization rules (line endings, soft hyphens, trailing spaces, blank-line collapse, NFKC), the HTML page keeping headings and table rows while dropping scripts, styles, nav, and footer, document metadata, failing closed for an unlisted file, and rejecting unsupported types.
- **Deduplication**: shingles and Jaccard on worked values, the near-duplicate travel policy being dropped in favor of the newer one, and an exact duplicate being reported as `exact`.
- **Chunking**: fixed windows' offsets and overlap, heading paths (including the skipped empty heading and a preamble), structure-aware chunks staying within the limit, never crossing a heading, overlapping on word boundaries, and short sections staying whole; `make_chunks` copying metadata without mutating the document.
- **Vector store**: a normalized, deterministic embedder; HR-only chunks never reaching a non-HR caller; `allowed_groups` being required; ranking order and the `where` filter; upsert replacing rather than duplicating; delete; JSON round trip; and NumPy and pure Python scores matching.
- **Statistics**: exact stats on a small example, and on the real corpus, that fixed windows start mid-word somewhere while structure-aware chunks never do.

What they don't check: retrieval quality (the embedder is a stand-in), headings inside code fences (see `CHANGE.md`), what happens when an edited document gets a new `doc_id` and its old chunks remain, malformed HTML beyond the sample page, or performance on a large corpus.

## Review questions

1. An AI changes the `groups` line in `load_document` to `sorted(entry.get("groups", ["all-staff"]))` "so new files show up in search". What is the risk, and would the tests catch it?

<details>
<summary>Answer</summary>

Any file without a manifest entry becomes visible to all staff, including a sensitive file someone drops into the folder by mistake. That is failing open. `test_unlisted_document_fails_closed` catches it, because it asserts that an unlisted file gets no groups. The right fix for "new files don't show up" is adding them to the manifest.
</details>

2. Someone "simplifies" `query` to rank all records, take the top k, and then remove the ones the caller can't see. Give two ways this goes wrong.

<details>
<summary>Answer</summary>

First, it can return too few results: if the top k are all restricted, the caller gets nothing even though visible matches exist further down. Second, the restricted data now flows through the ranking step and the code path that returns it, so one forgotten filter (or a later edit that drops it) leaks it. Filtering before ranking, inside the store, with a required argument, avoids both.
</details>

3. In `make_chunks`, what would happen if `meta = dict(doc.metadata)` were replaced by `meta = doc.metadata`?

<details>
<summary>Answer</summary>

Every chunk's metadata would be the same dictionary object as the document's. Each `update` would overwrite the previous chunk's `chunk_index`, `start`, and `end`, so all chunks would end up reporting the last chunk's offsets, and the document itself would gain a `strategy` key. `test_make_chunks_propagates_metadata` catches both problems.
</details>

4. The incident runbook is edited and re-ingested. Why does the store end up with both the old and new chunks, and what should the ingestion code do about it?

<details>
<summary>Answer</summary>

`doc_id` is derived from the content hash, so edited text gets a new id, and its chunk ids (`doc_id:strategy:index`) don't match the old ones. `upsert` therefore adds new records instead of replacing the old ones. The ingestion step needs to track which `doc_id` each source file had last time (for example, by `source`) and call `delete_document` on the old id before or after upserting the new chunks.
</details>

5. Why does `chunk_fixed` raise `ValueError` when `overlap >= size`?

<details>
<summary>Answer</summary>

The step between windows is `size - overlap`. If it is zero, `pos` never advances and the loop runs forever; if negative, it moves backward. Rejecting the parameters up front turns a hang into a clear error.
</details>
