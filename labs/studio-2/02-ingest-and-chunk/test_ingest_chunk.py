"""Tests for Studio 2, lab 02. Everything here runs offline; no API key needed.

Run:  pytest studio-2/02-ingest-and-chunk -q
"""
from __future__ import annotations

import json
import math
import pathlib

import pytest

import starter as lab

DOCS = pathlib.Path(__file__).parent / "docs"

MARKDOWN = """# Guide

Intro paragraph for the whole guide.

## Time off

### Vacation

Staff accrue vacation monthly. Request it three weeks ahead in peak season.

### Sick days

No note is needed for up to three days. Tell your manager before the shift.

## Equipment

Boots and vests are required on the warehouse floor. Report injuries the same day.
"""


def long_section(n_sentences: int = 30) -> str:
    body = " ".join(f"Sentence number {i} explains one more rule about returns and refunds." for i in range(n_sentences))
    return "# Policy\n\n## Returns\n\n" + body + "\n\n## Refunds\n\nRefunds go to the original payment method.\n"


# ---------------------------------------------------------------- 1. parsing and cleaning


def test_normalize_text_cleans_without_changing_words():
    raw = "Line one   \r\nLine­ two\r\n\r\n\r\n\r\nLine three\n\n"
    assert lab.normalize_text(raw) == "Line one\nLine two\n\nLine three\n"


def test_normalize_text_applies_nfkc():
    # U+FB01 is the "fi" ligature that PDF extractors often produce.
    assert lab.normalize_text("ﬁle") == "file\n"


def test_html_keeps_content_and_drops_boilerplate():
    doc = lab.load_document(DOCS / "returns-policy.html", lab.load_manifest(DOCS))
    assert "# Customer returns policy" in doc.text
    assert "## Used gear" in doc.text
    assert "| Unused, no receipt | 60 days | Store credit |" in doc.text, "table rows should survive as text"
    for junk in ("window.analytics", "font-family", "Cookie settings", "Home"):
        assert junk not in doc.text, f"boilerplate {junk!r} leaked into the text"


def test_load_document_metadata():
    doc = lab.load_document(DOCS / "incident-runbook.md", lab.load_manifest(DOCS))
    m = doc.metadata
    assert m["source"] == "incident-runbook.md", "source should be the file name, not an absolute path"
    assert m["title"] == "Warehouse Systems Incident Runbook"
    assert m["date"] == "2026-10-15"
    assert m["groups"] == ["ops"]
    assert m["format"] == "markdown"
    assert m["content_hash"] == lab.content_hash(doc.text)
    assert doc.doc_id == m["content_hash"][:12]


def test_unlisted_document_fails_closed(tmp_path):
    path = tmp_path / "stray-notes.md"
    path.write_text("# Notes\n\nSomeone dropped this file in the folder.\n")
    doc = lab.load_document(path, manifest={})
    assert doc.metadata["groups"] == [], "a file with no permissions entry must be visible to nobody"
    assert doc.metadata["title"] == "stray-notes"
    assert doc.metadata["date"] is None


def test_unsupported_type_raises(tmp_path):
    path = tmp_path / "deck.pptx"
    path.write_text("not really a deck")
    with pytest.raises(ValueError):
        lab.load_document(path, manifest={})


# ---------------------------------------------------------------- 2. deduplication


def test_jaccard_and_shingles():
    assert lab.jaccard(set(), set()) == 1.0
    assert lab.jaccard({1, 2}, {2, 3}) == pytest.approx(1 / 3)
    assert lab.shingles("A b c d e f", n=5) == {("a", "b", "c", "d", "e"), ("b", "c", "d", "e", "f")}
    assert lab.shingles("too short", n=5) == {("too", "short")}


def test_dedupe_drops_near_copy_and_keeps_newest():
    kept, dropped = lab.dedupe(lab.load_corpus(DOCS))
    sources = {d.metadata["source"] for d in kept}
    assert "travel-policy.txt" in sources, "keep the most recently dated version"
    assert "travel-policy-copy.txt" not in sources
    assert dropped == [{"source": "travel-policy-copy.txt", "duplicate_of": "travel-policy.txt", "reason": "near"}]
    assert len(kept) == 5


def test_dedupe_exact_duplicate():
    a = lab.Document("a", "same text here\n", {"source": "a.md", "date": "2026-01-01", "content_hash": "h1"})
    b = lab.Document("b", "same text here\n", {"source": "b.md", "date": "2025-01-01", "content_hash": "h1"})
    kept, dropped = lab.dedupe([b, a])
    assert [d.metadata["source"] for d in kept] == ["a.md"]
    assert dropped == [{"source": "b.md", "duplicate_of": "a.md", "reason": "exact"}]


# ---------------------------------------------------------------- 3. chunking


def test_chunk_fixed_sizes_offsets_and_overlap():
    text = "abcdefghij" * 25  # 250 characters, no whitespace
    pieces = lab.chunk_fixed(text, size=100, overlap=20)
    assert [p["start"] for p in pieces] == [0, 80, 160]
    assert all(len(p["text"]) <= 100 for p in pieces)
    assert all(text[p["start"] : p["end"]] == p["text"] for p in pieces), "offsets must slice the source exactly"
    assert pieces[-1]["end"] == 250, "the last window must reach the end of the text"
    with pytest.raises(ValueError):
        lab.chunk_fixed(text, size=100, overlap=100)


def test_split_sections_heading_paths():
    sections = lab.split_sections(MARKDOWN)
    paths = [s["headings"] for s in sections]
    assert paths == [
        ["Guide"],
        ["Guide", "Time off", "Vacation"],
        ["Guide", "Time off", "Sick days"],
        ["Guide", "Equipment"],
    ], "'## Time off' has no body of its own, so it is skipped; its title lives on in the children's paths"
    assert MARKDOWN[sections[1]["start"] :].startswith("### Vacation")


def test_split_sections_preamble():
    sections = lab.split_sections("Loose intro text.\n\n# Title\n\nBody.\n")
    assert sections[0] == {"headings": [], "start": 0, "end": sections[1]["start"]}


def test_chunk_markdown_respects_headings_and_limits():
    text = long_section()
    pieces = lab.chunk_markdown(text, max_chars=300, overlap=60)
    assert all(len(p["text"]) <= 300 for p in pieces), "no chunk may exceed max_chars"
    assert all(text[p["start"] : p["end"]] == p["text"] for p in pieces), "offsets must slice the source exactly"
    for p in pieces:
        heading_lines = [ln for ln in p["text"].splitlines() if ln.startswith("#")]
        assert len(heading_lines) <= 1, "a chunk must not cross a heading"
        if heading_lines:
            assert p["text"].startswith("#"), "a heading can only appear at the start of a chunk"
    refunds = [p for p in pieces if p["headings"][-1:] == ["Refunds"]]
    assert len(refunds) == 1 and "original payment method" in refunds[0]["text"]
    returns = [p for p in pieces if p["headings"] == ["Policy", "Returns"]]
    assert len(returns) >= 3, "the long section should be split"
    for a, b in zip(returns, returns[1:]):
        assert b["start"] < a["end"], "consecutive chunks in one section should overlap"
        assert b["text"][0].isalnum() and not text[b["start"] - 1].isalnum(), "overlap should start on a word boundary"


def test_chunk_markdown_short_sections_stay_whole():
    pieces = lab.chunk_markdown(MARKDOWN, max_chars=500, overlap=50)
    assert len(pieces) == 4
    assert pieces[1]["text"].startswith("### Vacation") and pieces[1]["text"].endswith("peak season.")


def test_chunk_markdown_rejects_bad_overlap():
    with pytest.raises(ValueError):
        lab.chunk_markdown(MARKDOWN, max_chars=100, overlap=150)


def test_make_chunks_propagates_metadata():
    doc = lab.load_document(DOCS / "employee-handbook.md", lab.load_manifest(DOCS))
    chunks = lab.make_chunks(doc, "structure")
    assert len({c.chunk_id for c in chunks}) == len(chunks), "chunk ids must be unique"
    assert chunks[0].chunk_id == f"{doc.doc_id}:structure:0"
    for i, c in enumerate(chunks):
        assert c.metadata["source"] == "employee-handbook.md"
        assert c.metadata["groups"] == ["all-staff"]
        assert c.metadata["doc_id"] == doc.doc_id and c.metadata["chunk_index"] == i
        assert doc.text[c.metadata["start"] : c.metadata["end"]] == c.text, "every chunk must link back to its source"
    vacation = [c for c in chunks if c.metadata["headings"][-1:] == ["Vacation"]]
    assert vacation and "1.25 vacation days" in vacation[0].text
    assert doc.metadata.get("strategy") is None, "copy the metadata; don't mutate the document's dict"


# ---------------------------------------------------------------- 4. vector store


def build_store():
    docs, _ = lab.dedupe(lab.load_corpus(DOCS))
    embedder = lab.HashingEmbedder()
    chunks = [c for d in docs for c in lab.make_chunks(d, "structure")]
    store = lab.LocalVectorStore(embedder.dim)
    store.upsert(chunks, embedder.embed([lab.embedding_text(c) for c in chunks]))
    return store, embedder, docs


def test_embedder_is_normalized_and_deterministic():
    e = lab.HashingEmbedder(dim=64)
    v1, v2 = e.embed(["label printer failure", "label printer failure"])
    assert v1 == v2
    assert math.isclose(sum(x * x for x in v1), 1.0, rel_tol=1e-9)


def test_query_never_leaks_restricted_documents():
    store, embedder, _ = build_store()
    q = embedder.embed(["What are the salary bands for warehouse leads?"])[0]
    hits = store.query(q, k=50, allowed_groups={"all-staff", "ops"})
    assert hits, "there should be visible results"
    assert all(h["metadata"]["source"] != "salary-bands.md" for h in hits), "HR-only chunks leaked"
    hr = store.query(q, k=3, allowed_groups={"hr"})
    assert hr and all(h["metadata"]["source"] == "salary-bands.md" for h in hr)
    assert store.query(q, k=5, allowed_groups=set()) == [], "no groups means no results"


def test_query_requires_explicit_groups():
    store, embedder, _ = build_store()
    with pytest.raises(TypeError):
        store.query(embedder.embed(["vacation"])[0], k=3)  # allowed_groups must be keyword-only with no default
    with pytest.raises(ValueError):
        store.query(embedder.embed(["vacation"])[0], k=3, allowed_groups=None)


def test_query_ranking_and_where_filter():
    store, embedder, _ = build_store()
    q = embedder.embed(["restart the print-bridge service and switch the carrier to manual label mode"])[0]
    hits = store.query(q, k=3, allowed_groups={"ops"})
    assert hits[0]["metadata"]["headings"][-1] == "Label printer failures"
    assert [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True)
    only_html = store.query(q, k=10, allowed_groups={"all-staff"}, where={"format": "html"})
    assert only_html and all(h["metadata"]["format"] == "html" for h in only_html)


def test_upsert_replaces_and_delete_removes():
    store, embedder, docs = build_store()
    n = len(store)
    runbook = next(d for d in docs if d.metadata["source"] == "incident-runbook.md")
    chunks = lab.make_chunks(runbook, "structure")
    store.upsert(chunks, embedder.embed([lab.embedding_text(c) for c in chunks]))
    assert len(store) == n, "re-ingesting the same document must replace, not duplicate"
    removed = store.delete_document(runbook.doc_id)
    assert removed == len(chunks) and len(store) == n - len(chunks)
    q = embedder.embed(["label printer"])[0]
    assert all(h["metadata"]["doc_id"] != runbook.doc_id for h in store.query(q, k=50, allowed_groups={"ops", "all-staff"}))
    with pytest.raises(ValueError):
        store.upsert(chunks[:1], [[0.0] * 3])


def test_save_and_load_round_trip(tmp_path):
    store, embedder, _ = build_store()
    path = tmp_path / "index.json"
    store.save(path)
    assert json.loads(path.read_text())["dim"] == embedder.dim
    again = lab.LocalVectorStore.load(path)
    q = embedder.embed(["vacation days"])[0]
    a = store.query(q, k=3, allowed_groups={"all-staff"})
    b = again.query(q, k=3, allowed_groups={"all-staff"})
    assert [h["id"] for h in a] == [h["id"] for h in b]


def test_numpy_scoring_matches_pure_python():
    np = pytest.importorskip("numpy")
    rows = [[0.6, 0.8], [1.0, 0.0], [0.0, 1.0]]
    vec = [0.0, 1.0]
    assert lab._scores(rows, vec) == pytest.approx(list(np.asarray(rows) @ np.asarray(vec)))


# ---------------------------------------------------------------- 5. statistics


def test_chunk_stats():
    chunks = [lab.Chunk(str(i), "x" * n) for i, n in enumerate([50, 200, 300, 600])]
    s = lab.chunk_stats(chunks, max_chars=500)
    assert s == {"count": 4, "min": 50, "max": 600, "mean": 287.5, "median": 250.0, "over_limit": 1, "tiny": 1}
    assert lab.chunk_stats([])["count"] == 0


def test_both_strategies_report_on_the_corpus():
    docs, _ = lab.dedupe(lab.load_corpus(DOCS))
    fixed = [c for d in docs for c in lab.make_chunks(d, "fixed")]
    structure = [c for d in docs for c in lab.make_chunks(d, "structure")]
    sf, ss = lab.chunk_stats(fixed), lab.chunk_stats(structure)
    assert sf["over_limit"] == 0 and ss["over_limit"] == 0
    mid_word = sum(1 for c in fixed if c.metadata["start"] > 0 and d_text(docs, c)[c.metadata["start"] - 1].isalnum())
    assert mid_word > 0, "fixed-size windows ignore word boundaries; expect some chunks to start mid-word"
    assert all(not d_text(docs, c)[c.metadata["start"] - 1].isalnum() for c in structure if c.metadata["start"] > 0)


def d_text(docs, chunk):
    return next(d.text for d in docs if d.doc_id == chunk.metadata["doc_id"])
