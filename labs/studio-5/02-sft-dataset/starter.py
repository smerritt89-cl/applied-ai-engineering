"""Lab 02 (Studio 5): build a supervised fine-tuning dataset (your file: fill in the TODOs).

Pipeline:
    labeled source texts (data/sources.jsonl)
      -> validate every gold label (schema, verbatim evidence, owner in source, reviewed)
      -> drop exact and near-duplicate texts (word shingles + Jaccard)
      -> split train / val / test, stratified by document kind, keeping threads together
      -> check that no near-duplicate or thread crosses a split
      -> write train/val as chat JSONL, freeze the test set with a fingerprint
      -> validate the written JSONL the way a training job would
Optional live step: draft labels for new texts with Claude, marked as needing human review.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import random
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import pydantic
from pydantic import BaseModel, ConfigDict, Field, model_validator

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
LAB_DIR = pathlib.Path(__file__).parent
DATA_DIR = LAB_DIR / "data"
OUT_DIR = LAB_DIR / "out"

SYSTEM_PROMPT = """You extract action items from business documents such as emails, support tickets, meeting notes, and chat messages.
Return JSON with an "items" list. Include only commitments or requests the document states, copy evidence word for word,
use null for an owner or date the document does not give, and return an empty list when there are no action items."""

SPLITS = ("train", "val", "test")
DEFAULT_FRACTIONS = {"train": 0.7, "val": 0.15, "test": 0.15}
NEAR_DUP_THRESHOLD = 0.7
SHINGLE_SIZE = 5
CHARS_PER_TOKEN = 4  # rough estimate for English; use the real tokenizer before a training run


# ---------------------------------------------------------------- label schema (same task as Studio 1)


class ActionItem(BaseModel):
    """One commitment or request found in a document."""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=3, description="What will be done, as a short imperative phrase")
    owner: str | None = Field(description="Name of the person responsible, as written; null if no person is named")
    owner_missing_reason: str | None = Field(description="If owner is null, a few words on why; otherwise null")
    due_date: date | None = Field(description="ISO date, only if the document states a specific calendar date")
    due_phrase: str | None = Field(description="The deadline wording copied from the document, or null")
    priority: Literal["high", "medium", "low"] = Field(description="Urgency signaled by the document")
    evidence: str = Field(min_length=10, description="A verbatim quote from the document that shows the item")

    @model_validator(mode="after")
    def _owner_or_reason(self) -> "ActionItem":
        if self.owner is None and not (self.owner_missing_reason or "").strip():
            raise ValueError("owner_missing_reason is required when owner is null")
        return self


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ActionItem] = Field(description="Every action item in the document; empty if none")


# ---------------------------------------------------------------- loading


def load_jsonl(path: pathlib.Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------- 1. validate gold labels


def normalize_ws(text: str) -> str:
    """Collapse every run of whitespace into one space and strip the ends."""
    # TODO: implement (see the docstring)
    raise NotImplementedError


def validate_record(record: dict) -> list[str]:
    """Return the problems with one labeled record (an empty list means it is usable).

    Problems, in this order:
      "label not reviewed"                   record["label_status"] == "needs_review"
      "schema: <loc>: <msg>"                 one per Pydantic error when record["label"] fails Extraction
      "item <i>: evidence not found in source"   (only checked when the schema passed)
      "item <i>: owner not found in source"      owner set but not a substring of the text
    Evidence and text are compared after normalize_ws, as exact substrings.
    """
    # TODO: implement (see the docstring)
    raise NotImplementedError


# ---------------------------------------------------------------- 2. near-duplicate detection


def normalize_for_dedup(text: str) -> str:
    """Lowercase, replace every character that is not a word character, whitespace, or apostrophe
    with a space, then collapse whitespace."""
    # TODO: implement (see the docstring)
    raise NotImplementedError


def shingles(text: str, k: int = SHINGLE_SIZE) -> set[str]:
    """The set of k-word shingles of normalize_for_dedup(text), each joined with single spaces.
    A text with fewer than k words yields one shingle: all of its words (or an empty set if it has none)."""
    # TODO: implement (see the docstring)
    raise NotImplementedError


def jaccard(a: set, b: set) -> float:
    """|a intersect b| / |a union b|, and 0.0 when both are empty."""
    # TODO: implement (see the docstring)
    raise NotImplementedError


def dedupe(records: list[dict], threshold: float = NEAR_DUP_THRESHOLD) -> tuple[list[dict], list[dict]]:
    """Keep the first record of every near-duplicate cluster, in input order.

    A record is dropped when its shingle Jaccard similarity with any already-kept record is >= threshold.
    Returns (kept, dropped), where each dropped entry is
    {"id": ..., "duplicate_of": <kept id>, "jaccard": <float rounded to 3 places>}.
    If several kept records qualify, report the most similar one.
    """
    # TODO: implement (see the docstring)
    raise NotImplementedError


# ---------------------------------------------------------------- 3. stratified, group-aware split


def stratified_group_split(
    records: list[dict],
    fractions: dict[str, float] = DEFAULT_FRACTIONS,
    strata_key: str = "kind",
    group_key: str = "thread",
    seed: int = 13,
) -> dict[str, list[dict]]:
    """Split records into train/val/test so that every group (thread) lands in exactly one split
    and each stratum (kind) is spread across splits in roughly the given fractions.

    Algorithm (deterministic for a given seed):
      - Group records by record[group_key]. Every record in a group must share record[strata_key];
        raise ValueError otherwise.
      - rng = random.Random(seed). For each stratum in sorted order: take its group ids sorted,
        then rng.shuffle them. Let n = number of records in the stratum.
        Fill "test" with whole groups (in shuffled order) until it holds at least
        round(n * fractions["test"]) records, then fill "val" the same way, then put the rest in "train".
      - Within each split, keep records in the original input order.
    """
    # TODO: implement (see the docstring)
    raise NotImplementedError


def check_split_leakage(
    splits: dict[str, list[dict]], threshold: float = NEAR_DUP_THRESHOLD, group_key: str = "thread"
) -> list[dict]:
    """Find pairs of records in DIFFERENT splits that share a group or are near-duplicates.

    Return a list of {"a": (split, id), "b": (split, id), "reason": "same group" | "near-duplicate"},
    one per offending pair, comparing splits in SPLITS order (train before val before test).
    """
    # TODO: implement (see the docstring)
    raise NotImplementedError


# ---------------------------------------------------------------- 4. chat-format examples


def user_message(text: str) -> str:
    return f"<document>\n{text}\n</document>\n\nExtract the action items from this document."


def to_chat_example(record: dict, system_prompt: str = SYSTEM_PROMPT) -> dict:
    """One training example in the chat ("messages") format used by OpenAI SFT and TRL's SFTTrainer.

    {"messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message(record["text"])},
        {"role": "assistant", "content": <the label as compact JSON>}]}
    The assistant content is json.dumps(record["label"], ensure_ascii=False, sort_keys=True), so
    identical labels always serialize identically. Nothing else (no ids, no metadata) goes in the example.
    """
    # TODO: implement (see the docstring)
    raise NotImplementedError


def validate_chat_lines(lines: list[str], max_tokens: int = 4000) -> list[tuple[int, str]]:
    """Check JSONL training lines the way a fine-tuning job would, plus checks a job won't do for you.

    Returns (line_number, problem) pairs, line numbers starting at 1, in line order. Per line, stop at
    the first structural problem; otherwise report every content problem that applies:
      structural:  "invalid JSON" | "no messages list" | "unknown role <r>" | "system message not first"
                   | "roles must alternate user/assistant after an optional system message"
                   | "last message must be assistant" | "empty content"
      content:     "too long (~<n> tokens)"  estimated as total characters // CHARS_PER_TOKEN > max_tokens
                   "assistant output fails schema"   final assistant content is not a valid Extraction JSON
                   "label leaked into prompt"        final assistant content appears inside a system or user message
                   "duplicate of line <k>"           same messages (compared as canonical JSON) as an earlier line
    """
    # TODO: implement (see the docstring)
    raise NotImplementedError


def fingerprint(records: list[dict]) -> str:
    """SHA-256 hex digest of the records, order-independent: sort by id, then
    json.dumps(sorted_records, sort_keys=True, ensure_ascii=False) encoded as UTF-8."""
    # TODO: implement (see the docstring)
    raise NotImplementedError


# ---------------------------------------------------------------- 5. the build (provided in the starter)


@dataclass
class BuildReport:
    quarantined: dict[str, list[str]] = field(default_factory=dict)
    dropped: list[dict] = field(default_factory=list)
    splits: dict[str, list[dict]] = field(default_factory=dict)
    leakage: list[dict] = field(default_factory=list)
    test_fingerprint: str = ""

    def summary(self) -> str:
        lines = [f"quarantined {len(self.quarantined)}: {sorted(self.quarantined)}"]
        lines.append(f"dropped as duplicates {len(self.dropped)}: {[d['id'] for d in self.dropped]}")
        for s in SPLITS:
            kinds: dict[str, int] = defaultdict(int)
            for r in self.splits.get(s, []):
                kinds[r["kind"]] += 1
            lines.append(f"{s}: {len(self.splits.get(s, []))} {dict(sorted(kinds.items()))}")
        lines.append(f"cross-split leakage: {len(self.leakage)}")
        lines.append(f"test fingerprint: {self.test_fingerprint[:16]}...")
        return "\n".join(lines)


def build_dataset(records: list[dict], seed: int = 13) -> BuildReport:
    report = BuildReport()
    clean = []
    for r in records:
        problems = validate_record(r)
        if problems:
            report.quarantined[r["id"]] = problems
        else:
            clean.append(r)
    kept, report.dropped = dedupe(clean)
    report.splits = stratified_group_split(kept, seed=seed)
    report.leakage = check_split_leakage(report.splits)
    report.test_fingerprint = fingerprint(report.splits["test"])
    return report


def write_outputs(report: BuildReport, out_dir: pathlib.Path = OUT_DIR) -> None:
    """train.jsonl and val.jsonl in chat format; test.jsonl as raw records (inputs plus gold labels,
    never trained on); manifest.json with ids per split and the test fingerprint."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for s in ("train", "val"):
        with open(out_dir / f"{s}.jsonl", "w", encoding="utf-8") as f:
            for r in report.splits[s]:
                f.write(json.dumps(to_chat_example(r), ensure_ascii=False) + "\n")
    with open(out_dir / "test.jsonl", "w", encoding="utf-8") as f:
        for r in report.splits["test"]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    manifest = {
        "splits": {s: [r["id"] for r in report.splits[s]] for s in SPLITS},
        "test_fingerprint": report.test_fingerprint,
        "quarantined": report.quarantined,
        "dropped": report.dropped,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- 6. optional live step: model-drafted labels


class DraftFailed(Exception):
    pass


def draft_label(client, record: dict, model: str = MODEL) -> dict:
    """Draft a label for an unlabeled record with Claude. The result is NOT gold data.

    Call client.messages.parse(model=model, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": user_message(record["text"])}], output_format=Extraction).
    Raise DraftFailed if stop_reason is "refusal" or "max_tokens", or parsed_output is None.
    Return a copy of the record with:
      "label":        parsed_output.model_dump(mode="json")
      "label_status": "needs_review"
      "drafted_by":   model
      "draft_flags":  validate_record problems for the drafted label, ignoring "label not reviewed"
    """
    # TODO: implement (see the docstring)
    raise NotImplementedError


# ---------------------------------------------------------------- script


def main() -> None:
    records = load_jsonl(DATA_DIR / "sources.jsonl")
    report = build_dataset(records)
    print(report.summary())
    for rid, problems in report.quarantined.items():
        print(f"  {rid}: {problems}")
    write_outputs(report)
    for s in ("train", "val"):
        lines = (OUT_DIR / f"{s}.jsonl").read_text(encoding="utf-8").splitlines()
        print(f"{s}.jsonl: {len(lines)} lines, {len(validate_chat_lines(lines))} problems")
    print(f"wrote {OUT_DIR}")


if __name__ == "__main__":
    main()
