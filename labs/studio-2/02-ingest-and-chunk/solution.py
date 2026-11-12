"""Lab 02 (Studio 2): ingest, chunk, embed, and store (reference solution).

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
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("­", "")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_manifest(docs_dir: pathlib.Path) -> dict:
    path = docs_dir / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_document(path: pathlib.Path, manifest: dict) -> Document:
    raw = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in (".html", ".htm"):
        text = html_to_text(raw)
        fmt = "html"
    elif suffix == ".md":
        text = normalize_text(raw)
        fmt = "markdown"
    elif suffix == ".txt":
        text = normalize_text(raw)
        fmt = "text"
    else:
        raise ValueError(f"unsupported file type: {path.name}")
    entry = manifest.get(path.name, {})
    metadata = {
        "source": path.name,
        "title": entry.get("title", path.stem),
        "date": entry.get("date"),
        "groups": sorted(entry.get("groups", [])),  # no manifest entry -> visible to nobody
        "format": fmt,
        "content_hash": content_hash(text),
    }
    return Document(doc_id=metadata["content_hash"][:12], text=text, metadata=metadata)


def load_corpus(docs_dir: pathlib.Path = DOCS_DIR) -> list[Document]:
    manifest = load_manifest(docs_dir)
    paths = sorted(p for p in docs_dir.iterdir() if p.suffix.lower() in SUPPORTED)
    return [load_document(p, manifest) for p in paths]


# ---------------------------------------------------------------- 2. deduplication


def shingles(text: str, n: int = 5) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.lower())
    if len(words) < n:
        return {tuple(words)} if words else set()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def dedupe(docs: list[Document], threshold: float = 0.8) -> tuple[list[Document], list[dict]]:
    # Policy: when two documents are duplicates, keep the most recently dated one.
    docs = sorted(docs, key=lambda d: d.metadata.get("date") or "", reverse=True)
    kept: list[Document] = []
    kept_shingles: list[set] = []
    dropped: list[dict] = []
    seen_hashes: dict[str, str] = {}
    for doc in docs:
        h = doc.metadata["content_hash"]
        if h in seen_hashes:
            dropped.append({"source": doc.metadata["source"], "duplicate_of": seen_hashes[h], "reason": "exact"})
            continue
        sh = shingles(doc.text)
        match = None
        for other, other_sh in zip(kept, kept_shingles):
            if jaccard(sh, other_sh) >= threshold:
                match = other
                break
        if match is not None:
            dropped.append(
                {"source": doc.metadata["source"], "duplicate_of": match.metadata["source"], "reason": "near"}
            )
            continue
        seen_hashes[h] = doc.metadata["source"]
        kept.append(doc)
        kept_shingles.append(sh)
    return kept, dropped


# ---------------------------------------------------------------- 3. chunking

HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def chunk_fixed(text: str, size: int, overlap: int) -> list[dict]:
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("need size > 0 and 0 <= overlap < size")
    spans = []
    step = size - overlap
    pos = 0
    while pos < len(text):
        start, end = _trim(text, pos, min(pos + size, len(text)))
        if end > start:
            spans.append({"start": start, "end": end, "text": text[start:end], "headings": []})
        if pos + size >= len(text):
            break
        pos += step
    return spans


def split_sections(text: str) -> list[dict]:
    matches = list(HEADING_RE.finditer(text))
    sections = []
    first = matches[0].start() if matches else len(text)
    if text[:first].strip():
        sections.append({"headings": [], "start": 0, "end": first})
    path: list[tuple[int, str]] = []
    for i, m in enumerate(matches):
        level = len(m.group(1))
        path = [p for p in path if p[0] < level] + [(level, m.group(2).strip())]
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        if not text[m.end() : end].strip():
            continue  # heading with no body of its own: its title still appears in the children's heading paths
        sections.append({"headings": [t for _, t in path], "start": m.start(), "end": end})
    return sections


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
    if max_chars <= 0 or not 0 <= overlap < max_chars:
        raise ValueError("need max_chars > 0 and 0 <= overlap < max_chars")
    out = []
    for sec in split_sections(text):
        for s, e in _pack(text, sec["start"], sec["end"], max_chars, overlap):
            out.append({"start": s, "end": e, "text": text[s:e], "headings": list(sec["headings"])})
    return out


STRATEGIES = {
    "fixed": lambda text: chunk_fixed(text, size=500, overlap=50),
    "structure": lambda text: chunk_markdown(text, max_chars=500, overlap=50),
}


def make_chunks(doc: Document, strategy: str) -> list[Chunk]:
    pieces = STRATEGIES[strategy](doc.text)
    chunks = []
    for i, piece in enumerate(pieces):
        meta = dict(doc.metadata)
        meta.update(
            {
                "doc_id": doc.doc_id,
                "strategy": strategy,
                "chunk_index": i,
                "start": piece["start"],
                "end": piece["end"],
                "headings": piece["headings"],
            }
        )
        chunks.append(Chunk(chunk_id=f"{doc.doc_id}:{strategy}:{i}", text=piece["text"], metadata=meta))
    return chunks


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
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        for chunk, vec in zip(chunks, vectors):
            if len(vec) != self.dim:
                raise ValueError(f"vector for {chunk.chunk_id} has {len(vec)} dims, expected {self.dim}")
            self.records[chunk.chunk_id] = {"text": chunk.text, "metadata": dict(chunk.metadata), "vector": list(vec)}

    def delete_document(self, doc_id: str) -> int:
        ids = [cid for cid, r in self.records.items() if r["metadata"].get("doc_id") == doc_id]
        for cid in ids:
            del self.records[cid]
        return len(ids)

    def query(self, vector: list[float], k: int, *, allowed_groups, where: dict | None = None) -> list[dict]:
        if allowed_groups is None:
            raise ValueError("allowed_groups is required: pass the caller's groups explicitly")
        allowed = set(allowed_groups)
        eligible = [
            (cid, r)
            for cid, r in self.records.items()
            if allowed & set(r["metadata"].get("groups", [])) and _matches(r["metadata"], where)
        ]
        if not eligible or k <= 0:
            return []
        scores = _scores([r["vector"] for _, r in eligible], vector)
        top = heapq.nlargest(k, range(len(eligible)), key=lambda i: scores[i])
        return [
            {"id": eligible[i][0], "score": scores[i], "text": eligible[i][1]["text"], "metadata": eligible[i][1]["metadata"]}
            for i in top
        ]

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
    if not chunks:
        return {"count": 0, "min": 0, "max": 0, "mean": 0.0, "median": 0.0, "over_limit": 0, "tiny": 0}
    lengths = [len(c.text) for c in chunks]
    return {
        "count": len(lengths),
        "min": min(lengths),
        "max": max(lengths),
        "mean": round(statistics.mean(lengths), 1),
        "median": float(statistics.median(lengths)),
        "over_limit": sum(n > max_chars for n in lengths),
        "tiny": sum(n < 100 for n in lengths),
    }


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
