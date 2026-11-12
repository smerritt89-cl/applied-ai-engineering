"""Lab 02 (Studio 5): build a supervised fine-tuning dataset (reference solution).

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
    return " ".join(text.split())


def validate_record(record: dict) -> list[str]:
    """Return the problems with one labeled record (an empty list means it is usable).

    Problems, in this order:
      "label not reviewed"                   record["label_status"] == "needs_review"
      "schema: <loc>: <msg>"                 one per Pydantic error when record["label"] fails Extraction
      "item <i>: evidence not found in source"   (only checked when the schema passed)
      "item <i>: owner not found in source"      owner set but not a substring of the text
    Evidence and text are compared after normalize_ws, as exact substrings.
    """
    problems: list[str] = []
    if record.get("label_status") == "needs_review":
        problems.append("label not reviewed")
    try:
        extraction = Extraction.model_validate(record["label"])
    except pydantic.ValidationError as err:
        for e in err.errors():
            where = ".".join(str(p) for p in e["loc"]) or "(root)"
            problems.append(f"schema: {where}: {e['msg']}")
        return problems
    source = normalize_ws(record["text"])
    for i, item in enumerate(extraction.items):
        quote = normalize_ws(item.evidence)
        if not quote or quote not in source:
            problems.append(f"item {i}: evidence not found in source")
        if item.owner is not None and normalize_ws(item.owner) not in source:
            problems.append(f"item {i}: owner not found in source")
    return problems


# ---------------------------------------------------------------- 2. near-duplicate detection


def normalize_for_dedup(text: str) -> str:
    """Lowercase, replace every character that is not a word character, whitespace, or apostrophe
    with a space, then collapse whitespace."""
    return normalize_ws(re.sub(r"[^\w\s']", " ", text.lower()))


def shingles(text: str, k: int = SHINGLE_SIZE) -> set[str]:
    """The set of k-word shingles of normalize_for_dedup(text), each joined with single spaces.
    A text with fewer than k words yields one shingle: all of its words (or an empty set if it has none)."""
    words = normalize_for_dedup(text).split()
    if not words:
        return set()
    if len(words) < k:
        return {" ".join(words)}
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def jaccard(a: set, b: set) -> float:
    """|a intersect b| / |a union b|, and 0.0 when both are empty."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedupe(records: list[dict], threshold: float = NEAR_DUP_THRESHOLD) -> tuple[list[dict], list[dict]]:
    """Keep the first record of every near-duplicate cluster, in input order.

    A record is dropped when its shingle Jaccard similarity with any already-kept record is >= threshold.
    Returns (kept, dropped), where each dropped entry is
    {"id": ..., "duplicate_of": <kept id>, "jaccard": <float rounded to 3 places>}.
    If several kept records qualify, report the most similar one.
    """
    kept: list[dict] = []
    kept_shingles: list[set] = []
    dropped: list[dict] = []
    for r in records:
        s = shingles(r["text"])
        best_j, best_id = 0.0, None
        for other, other_s in zip(kept, kept_shingles):
            j = jaccard(s, other_s)
            if j > best_j:
                best_j, best_id = j, other["id"]
        if best_id is not None and best_j >= threshold:
            dropped.append({"id": r["id"], "duplicate_of": best_id, "jaccard": round(best_j, 3)})
        else:
            kept.append(r)
            kept_shingles.append(s)
    return kept, dropped


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
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[r[group_key]].append(r)
    strata: dict[str, list[str]] = defaultdict(list)
    for gid, members in groups.items():
        kinds = {m[strata_key] for m in members}
        if len(kinds) != 1:
            raise ValueError(f"group {gid} mixes strata: {sorted(kinds)}")
        strata[kinds.pop()].append(gid)

    rng = random.Random(seed)
    assignment: dict[str, str] = {}
    for stratum in sorted(strata):
        gids = sorted(strata[stratum])
        rng.shuffle(gids)
        n = sum(len(groups[g]) for g in gids)
        targets = {"test": round(n * fractions["test"]), "val": round(n * fractions["val"])}
        counts = {"test": 0, "val": 0}
        for gid in gids:
            for split in ("test", "val"):
                if counts[split] < targets[split]:
                    assignment[gid] = split
                    counts[split] += len(groups[gid])
                    break
            else:
                assignment[gid] = "train"

    out: dict[str, list[dict]] = {s: [] for s in SPLITS}
    for r in records:
        out[assignment[r[group_key]]].append(r)
    return out


def check_split_leakage(
    splits: dict[str, list[dict]], threshold: float = NEAR_DUP_THRESHOLD, group_key: str = "thread"
) -> list[dict]:
    """Find pairs of records in DIFFERENT splits that share a group or are near-duplicates.

    Return a list of {"a": (split, id), "b": (split, id), "reason": "same group" | "near-duplicate"},
    one per offending pair, comparing splits in SPLITS order (train before val before test).
    """
    problems = []
    names = [s for s in SPLITS if s in splits]
    cache = {r["id"]: shingles(r["text"]) for s in names for r in splits[s]}
    for i, sa in enumerate(names):
        for sb in names[i + 1 :]:
            for ra in splits[sa]:
                for rb in splits[sb]:
                    if ra.get(group_key) is not None and ra.get(group_key) == rb.get(group_key):
                        reason = "same group"
                    elif jaccard(cache[ra["id"]], cache[rb["id"]]) >= threshold:
                        reason = "near-duplicate"
                    else:
                        continue
                    problems.append({"a": (sa, ra["id"]), "b": (sb, rb["id"]), "reason": reason})
    return problems


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
    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message(record["text"])},
            {"role": "assistant", "content": json.dumps(record["label"], ensure_ascii=False, sort_keys=True)},
        ]
    }


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
    problems: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    for n, line in enumerate(lines, start=1):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            problems.append((n, "invalid JSON"))
            continue
        msgs = obj.get("messages") if isinstance(obj, dict) else None
        if not isinstance(msgs, list) or not msgs:
            problems.append((n, "no messages list"))
            continue
        structural = None
        for i, m in enumerate(msgs):
            role = m.get("role") if isinstance(m, dict) else None
            if role not in ("system", "user", "assistant"):
                structural = f"unknown role {role}"
                break
            if role == "system" and i != 0:
                structural = "system message not first"
                break
            if not isinstance(m.get("content"), str) or not m["content"].strip():
                structural = "empty content"
                break
        if structural is None:
            turns = [m["role"] for m in msgs if m["role"] != "system"]
            alternates = all(t == ("user" if i % 2 == 0 else "assistant") for i, t in enumerate(turns))
            if not alternates:
                structural = "roles must alternate user/assistant after an optional system message"
            elif not turns or turns[-1] != "assistant":
                structural = "last message must be assistant"
        if structural:
            problems.append((n, structural))
            continue

        total_chars = sum(len(m["content"]) for m in msgs)
        if total_chars // CHARS_PER_TOKEN > max_tokens:
            problems.append((n, f"too long (~{total_chars // CHARS_PER_TOKEN} tokens)"))
        answer = msgs[-1]["content"]
        try:
            Extraction.model_validate_json(answer)
        except pydantic.ValidationError:
            problems.append((n, "assistant output fails schema"))
        if any(m["role"] != "assistant" and answer.strip() in m["content"] for m in msgs[:-1]):
            problems.append((n, "label leaked into prompt"))
        key = json.dumps(msgs, sort_keys=True, ensure_ascii=False)
        if key in seen:
            problems.append((n, f"duplicate of line {seen[key]}"))
        else:
            seen[key] = n
    return problems


def fingerprint(records: list[dict]) -> str:
    """SHA-256 hex digest of the records, order-independent: sort by id, then
    json.dumps(sorted_records, sort_keys=True, ensure_ascii=False) encoded as UTF-8."""
    ordered = sorted(records, key=lambda r: r["id"])
    return hashlib.sha256(json.dumps(ordered, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


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
    response = client.messages.parse(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message(record["text"])}],
        output_format=Extraction,
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        raise DraftFailed(f"stop_reason={response.stop_reason} for {record['id']}")
    if response.parsed_output is None:
        raise DraftFailed(f"no parsed output for {record['id']}")
    drafted = dict(record)
    drafted["label"] = response.parsed_output.model_dump(mode="json")
    drafted["label_status"] = "needs_review"
    drafted["drafted_by"] = model
    drafted["draft_flags"] = [p for p in validate_record(drafted) if p != "label not reviewed"]
    return drafted


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
