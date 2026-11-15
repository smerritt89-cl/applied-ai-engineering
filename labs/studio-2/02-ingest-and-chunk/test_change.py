"""Acceptance tests for this lab's CHANGE.md task: lines inside fenced code blocks are not headings.

Run:  pytest studio-2/02-ingest-and-chunk/test_change.py -q
These fail until the change is made in work.py (they are skipped in a normal full run).
"""
from __future__ import annotations

import pytest

import starter as lab

pytestmark = pytest.mark.change

FENCED = """# Setup guide

Install the tools before your first shift.

## Install

Run these commands:

```bash
# install deps
pip install -r requirements.txt
## not a heading either
```

Then sign in.

## Verify

Open the dashboard and check the status light.
"""

TILDE = """# Notes

~~~
# inside a tilde fence
```
# still inside: a backtick line does not close a tilde fence
~~~

## After
Body after the fence.
"""


def test_comment_lines_in_a_fence_are_not_headings():
    paths = [s["headings"] for s in lab.split_sections(FENCED)]
    assert paths == [["Setup guide"], ["Setup guide", "Install"], ["Setup guide", "Verify"]]


def test_the_code_block_stays_in_its_section():
    sections = lab.split_sections(FENCED)
    install = next(s for s in sections if s["headings"][-1:] == ["Install"])
    body = FENCED[install["start"] : install["end"]]
    assert "# install deps" in body and "Then sign in." in body


def test_fence_markers_must_match():
    paths = [s["headings"] for s in lab.split_sections(TILDE)]
    assert paths == [["Notes"], ["Notes", "After"]]


def test_unclosed_fence_runs_to_the_end():
    text = "# Title\n\nIntro.\n\n```\n# never closed\n## also code\n"
    assert [s["headings"] for s in lab.split_sections(text)] == [["Title"]]


def test_chunk_markdown_keeps_the_fence_with_its_heading():
    pieces = lab.chunk_markdown(FENCED, max_chars=500, overlap=50)
    assert [p["headings"] for p in pieces] == [["Setup guide"], ["Setup guide", "Install"], ["Setup guide", "Verify"]]
    assert all(FENCED[p["start"] : p["end"]] == p["text"] for p in pieces)


def test_documents_without_fences_are_unchanged():
    text = "# Guide\n\nIntro.\n\n## A\n\nBody A.\n\n## B\n\nBody B.\n"
    assert [s["headings"] for s in lab.split_sections(text)] == [["Guide"], ["Guide", "A"], ["Guide", "B"]]
