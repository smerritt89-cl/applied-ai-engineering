"""Lab 02 (Studio 2): ingest, chunk, embed, and store (your file: fill in the TODOs).

Pipeline:
    files in docs/ -> text (HTML stripped of boilerplate) -> normalized text + metadata
                   -> exact and near-duplicate removal
                   -> chunks (fixed-size or structure-aware), each with offsets back into the source
                   -> embeddings (a local hashing embedder, swappable for a real model)
                   -> a small vector store with access filtering, upserts, deletes, and JSON persistence
                   -> chunk statistics for each strategy

Everything runs offline with the standard library. NumPy is used for search if it is installed.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import math
import pathlib
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser

DOCS_DIR = pathlib.Path(__file__).parent / "docs"
SUPPORTED = {".md", ".txt", ".html", ".htm"}


@dataclass
class Document:
    doc_id: str
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------- 1. parsing and cleaning


class _HTMLToText(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "head", "noscript"}
    BLOCK = {"p", "div", "li", "section", "article", "main", "br", "table", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []
        elif tag in self.BLOCK:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag in ("td", "th") and self.row is not None and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.parts.append("\n| " + " | ".join(self.row) + " |")
            self.row = None
        elif re.fullmatch(r"h[1-6]", tag) or tag in self.BLOCK:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.cell is not None:
            self.cell.append(data)
        else:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _HTMLToText()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts)
    # Collapse runs of spaces inside lines, but keep line structure.
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return normalize_text("\n".join(lines))


def normalize_text(text: str) -> str:
    r"""Clean extracted text without changing its words.

    Apply, in order: Unicode NFKC normalization; convert Windows (\r\n) and old Mac (\r) line endings to \n;
    remove soft hyphens (\u00ad); strip trailing whitespace from every line; collapse three or more consecutive
    newlines into exactly two; strip the ends and finish with a single trailing newline.
    """
    # TODO: implement
    raise NotImplementedError


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_manifest(docs_dir: pathlib.Path) -> dict:
    path = docs_dir / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_document(path: pathlib.Path, manifest: dict) -> Document:
    """Read one file and return a Document with text and metadata.

    - .html/.htm -> html_to_text (format "html"); .md -> normalize_text (format "markdown");
      .txt -> normalize_text (format "text"); anything else -> ValueError.
    - metadata keys: source (file name only), title (manifest title, else the file stem), date (manifest date or
      None), groups (sorted list from the manifest; [] when the file has no manifest entry, so nobody can see it),
      format, content_hash (content_hash of the cleaned text).
    - doc_id is the first 12 characters of content_hash.
    """
    # TODO: implement
    raise NotImplementedError


def load_corpus(docs_dir: pathlib.Path = DOCS_DIR) -> list[Document]:
    manifest = load_manifest(docs_dir)
    paths = sorted(p for p in docs_dir.iterdir() if p.suffix.lower() in SUPPORTED)
    return [load_document(p, manifest) for p in paths]


# ---------------------------------------------------------------- 2. deduplication


def shingles(text: str, n: int = 5) -> set[tuple[str, ...]]:
    r"""Return the set of word n-grams (tuples) of the lowercased text, using re.findall(r"\w+", ...) for words.
    If the text has fewer than n words, return a set holding one tuple of all its words (or an empty set)."""
    # TODO: implement
    raise NotImplementedError


def jaccard(a: set, b: set) -> float:
    """|a & b| / |a | b|, and 1.0 when both sets are empty."""
    # TODO: implement
    raise NotImplementedError


def dedupe(docs: list[Document], threshold: float = 0.8) -> tuple[list[Document], list[dict]]:
    # Policy: when two documents are duplicates, keep the most recently dated one.
    """Remove exact and near-duplicate documents. Returns (kept, dropped).

    Policy: when two documents are duplicates, keep the most recently dated one, so process documents sorted by
    metadata["date"] descending (treat None as ""). A document is an exact duplicate if its content_hash was already
    kept, and a near duplicate if the Jaccard similarity of its shingles with any kept document is >= threshold.
    Each dropped entry is {"source": ..., "duplicate_of": <source of the kept document>, "reason": "exact" | "near"}.
    """
    # TODO: implement
    raise NotImplementedError


# ---------------------------------------------------------------- 3. chunking

HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def chunk_fixed(text: str, size: int, overlap: int) -> list[dict]:
    """Fixed-size windows of `size` characters, each starting `size - overlap` after the previous one.

    Raise ValueError unless size > 0 and 0 <= overlap < size. Trim whitespace from both ends of each window with
    _trim and skip empty windows. Stop after the window that reaches the end of the text.
    Each piece is {"start": s, "end": e, "text": text[s:e], "headings": []}.
    """
    # TODO: implement
    raise NotImplementedError


def split_sections(text: str) -> list[dict]:
    """Split Markdown into sections at ATX headings (HEADING_RE), tracking the heading path.

    Returns a list of {"headings": [...], "start": ..., "end": ...} covering the text, where a section runs from its
    heading line to the next heading (of any level). The heading path holds the titles of the enclosing headings:
    a level-3 heading under "Time off" (level 2) under the H1 title gets [title, "Time off", "Vacation"].
    Text before the first heading, if not blank, is a section with headings [] starting at 0.
    Skip a section whose body (the text after its heading line) is blank.
    """
    # TODO: implement
    raise NotImplementedError


def _best_break(text: str, pos: int, limit: int, min_len: int) -> int:
    for sep in ("\n\n", "\n", ". ", " "):
        idx = text.rfind(sep, pos + min_len, limit)
        if idx != -1:
            return idx + len(sep)
    return limit


def _pack(text: str, start: int, end: int, max_chars: int, overlap: int) -> list[tuple[int, int]]:
    start, end = _trim(text, start, end)
    if end <= start:
        return []
    if end - start <= max_chars:
        return [(start, end)]
    spans = []
    pos = start
    while pos < end:
        limit = min(pos + max_chars, end)
        cut = end if limit == end else _best_break(text, pos, limit, max(1, max_chars // 4))
        s, e = _trim(text, pos, cut)
        if e > s:
            spans.append((s, e))
        if cut >= end:
            break
        nxt = max(cut - overlap, pos + 1)
        while nxt < cut and not text[nxt - 1].isspace():  # start the overlap on a word boundary
            nxt += 1
        while nxt < end and text[nxt].isspace():
            nxt += 1
        pos = nxt
    return spans


def chunk_markdown(text: str, max_chars: int, overlap: int) -> list[dict]:
    """Structure-aware chunking: split into sections, then pack each section with _pack.

    Raise ValueError unless max_chars > 0 and 0 <= overlap < max_chars. A chunk never crosses a section boundary.
    Each piece is {"start": s, "end": e, "text": text[s:e], "headings": <the section's heading path>}.
    """
    # TODO: implement
    raise NotImplementedError


STRATEGIES = {
    "fixed": lambda text: chunk_fixed(text, size=500, overlap=50),
    "structure": lambda text: chunk_markdown(text, max_chars=500, overlap=50),
}


def make_chunks(doc: Document, strategy: str) -> list[Chunk]:
    """Chunk a Document with STRATEGIES[strategy] and wrap each piece in a Chunk.

    chunk_id is f"{doc_id}:{strategy}:{i}". metadata is a copy of the document's metadata plus doc_id, strategy,
    chunk_index, start, end, and headings.
    """
    # TODO: implement
    raise NotImplementedError


def embedding_text(chunk: Chunk) -> str:
    """What gets embedded: title and heading path, then the chunk. The stored text stays an exact source slice."""
    header = " > ".join([chunk.metadata.get("title", "")] + chunk.metadata.get("headings", []))
    return f"{header}\n{chunk.text}" if header.strip() else chunk.text


# ---------------------------------------------------------------- 4. embeddings


class HashingEmbedder:
    """A deterministic stand-in for an embedding model: hashed word unigrams and bigrams, L2-normalized.

    It captures word overlap, not meaning. Use it to test the pipeline offline, then swap in a real model.
    """

    def __init__(self, dim: int = 512):
        self.dim = dim

    def _index(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        return value % self.dim, (1.0 if (value >> 63) & 1 else -1.0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            words = re.findall(r"\w+", text.lower())
            features = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
            for feat in features:
                i, sign = self._index(feat)
                vec[i] += sign
            norm = math.sqrt(sum(x * x for x in vec))
            out.append([x / norm for x in vec] if norm else vec)
        return out


# ---------------------------------------------------------------- 5. vector store


def _matches(meta: dict, where: dict | None) -> bool:
    if not where:
        return True
    return all(meta.get(k) == v for k, v in where.items())


class LocalVectorStore:
    """Brute-force cosine search over normalized vectors, with access control applied before ranking."""

    def __init__(self, dim: int):
        self.dim = dim
        self.records: dict[str, dict] = {}

    def __len__(self):
        return len(self.records)

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Insert or replace records by chunk_id. Raise ValueError if the lengths differ or a vector has the wrong
        dimension. Store {"text", "metadata" (a copy), "vector" (a list)} under self.records[chunk_id]."""
        # TODO: implement
        raise NotImplementedError

    def delete_document(self, doc_id: str) -> int:
        """Delete every record whose metadata doc_id matches. Return how many were deleted."""
        # TODO: implement
        raise NotImplementedError

    def query(self, vector: list[float], k: int, *, allowed_groups, where: dict | None = None) -> list[dict]:
        """Return up to k results, best first, as {"id", "score", "text", "metadata"}.

        Access control comes first: a record is eligible only if its metadata "groups" share at least one group with
        allowed_groups, and it matches every key in `where` (exact equality). allowed_groups has no default; raise
        ValueError if it is None. Score eligible records with _scores (dot product; vectors are normalized, so this is
        cosine similarity) and keep the top k.
        """
        # TODO: implement
        raise NotImplementedError

    def save(self, path: pathlib.Path) -> None:
        payload = {"dim": self.dim, "records": self.records}
        pathlib.Path(path).write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: pathlib.Path) -> "LocalVectorStore":
        payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        store = cls(payload["dim"])
        store.records = payload["records"]
        return store


def _scores(matrix: list[list[float]], vector: list[float]) -> list[float]:
    try:
        import numpy as np
    except ImportError:
        return [sum(a * b for a, b in zip(row, vector)) for row in matrix]
    return (np.asarray(matrix, dtype=float) @ np.asarray(vector, dtype=float)).tolist()


# ---------------------------------------------------------------- 6. statistics


def chunk_stats(chunks: list[Chunk], max_chars: int = 500) -> dict:
    """Summary statistics of chunk lengths in characters.

    Keys: count, min, max, mean (rounded to 1 decimal), median (a float), over_limit (chunks longer than max_chars),
    tiny (chunks shorter than 100 characters). For no chunks, return zeros for every key.
    """
    # TODO: implement
    raise NotImplementedError


def build_index(docs: list[Document], strategy: str, embedder: HashingEmbedder) -> tuple[LocalVectorStore, list[Chunk]]:
    chunks = [c for d in docs for c in make_chunks(d, strategy)]
    store = LocalVectorStore(embedder.dim)
    store.upsert(chunks, embedder.embed([embedding_text(c) for c in chunks]))
    return store, chunks


def main() -> None:
    docs, dropped = dedupe(load_corpus())
    print(f"Loaded {len(docs)} documents; dropped {len(dropped)} duplicates: {dropped}\n")
    embedder = HashingEmbedder()
    query = "What should I do if label printing fails for one carrier?"
    for strategy in STRATEGIES:
        store, chunks = build_index(docs, strategy, embedder)
        print(strategy, chunk_stats(chunks))
        for hit in store.query(embedder.embed([query])[0], k=2, allowed_groups={"ops", "all-staff"}):
            m = hit["metadata"]
            print(f"  {hit['score']:.3f} {m['source']}[{m['start']}:{m['end']}] {' > '.join(m['headings'])}")
            print("   ", hit["text"][:120].replace("\n", " "), "...")
        print()
        store.save(pathlib.Path(__file__).parent / f"index-{strategy}.json")


if __name__ == "__main__":
    main()
