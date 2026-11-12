"""Tests for Studio 5, lab 02. Offline tests need no API key; @pytest.mark.live tests call Claude.

Run:  pytest studio-5/02-sft-dataset -q
"""
from __future__ import annotations

import copy
import json
import pathlib
from collections import Counter
from types import SimpleNamespace

import pytest

import starter as lab

DATA = pathlib.Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def records():
    return lab.load_jsonl(DATA / "sources.jsonl")


@pytest.fixture(scope="module")
def by_id(records):
    return {r["id"]: r for r in records}


def item(**overrides) -> dict:
    base = {
        "task": "Send the revised budget",
        "owner": "Priya",
        "owner_missing_reason": None,
        "due_date": None,
        "due_phrase": "by Friday",
        "priority": "medium",
        "evidence": "I'll send the revised budget by Friday.",
    }
    base.update(overrides)
    return base


def record(rid="x1", text="Priya: I'll send the revised budget by Friday.", items=None, **extra) -> dict:
    r = {"id": rid, "kind": "meeting", "thread": f"th-{rid}", "text": text,
         "label": {"items": [item()] if items is None else items}}
    r.update(extra)
    return r


# ---------------------------------------------------------------- 1. validating gold labels


def test_normalize_ws():
    assert lab.normalize_ws("  a \n b\t\tc ") == "a b c"


def test_valid_record_has_no_problems():
    assert lab.validate_record(record()) == []
    # An empty item list is a valid label: "no action items here" is something the model must learn.
    assert lab.validate_record(record(items=[])) == []


def test_evidence_matching_ignores_line_wrapping():
    wrapped = record(text="Priya: I'll send the revised\nbudget   by Friday.")
    assert lab.validate_record(wrapped) == []


def test_paraphrased_evidence_is_caught():
    bad = record(items=[item(evidence="Priya will send the revised budget by Friday.")])
    assert lab.validate_record(bad) == ["item 0: evidence not found in source"]


def test_unknown_owner_is_caught():
    bad = record(items=[item(owner="Jordan")])
    assert lab.validate_record(bad) == ["item 0: owner not found in source"]


def test_schema_errors_are_reported_with_location():
    bad = record(items=[item(owner=None, owner_missing_reason=None)])
    problems = lab.validate_record(bad)
    assert len(problems) == 1 and problems[0].startswith("schema: items.0"), problems
    extra = record(items=[item(assignee="Priya")])
    assert lab.validate_record(extra)[0].startswith("schema: items.0.assignee")
    wrong_priority = record(items=[item(priority="urgent")])
    assert lab.validate_record(wrong_priority)[0].startswith("schema: items.0.priority")


def test_model_drafted_labels_are_not_gold():
    drafted = record(label_status="needs_review")
    assert lab.validate_record(drafted) == ["label not reviewed"]
    reviewed = record(label_status="reviewed")
    assert lab.validate_record(reviewed) == []


def test_planted_label_errors_in_the_data(records):
    problems = {r["id"]: lab.validate_record(r) for r in records}
    bad = {rid for rid, p in problems.items() if p}
    assert bad == {"e12", "t12", "m12"}, f"expected exactly the three planted label errors, got {sorted(bad)}"
    assert problems["e12"] == ["item 0: evidence not found in source"]
    assert problems["m12"] == ["item 0: owner not found in source"]
    assert problems["t12"][0].startswith("schema:")


# ---------------------------------------------------------------- 2. near-duplicates


def test_normalize_for_dedup():
    assert lab.normalize_for_dedup("Hi, PRIYA!\nI'll  send it.") == "hi priya i'll send it"


def test_shingles():
    assert lab.shingles("a b c d e f", k=5) == {"a b c d e", "b c d e f"}
    assert lab.shingles("Too short", k=5) == {"too short"}
    assert lab.shingles("  ...  ", k=5) == set()


def test_jaccard():
    assert lab.jaccard({1, 2, 3}, {2, 3, 4}) == pytest.approx(0.5)
    assert lab.jaccard(set(), set()) == 0.0
    assert lab.jaccard({1}, {1}) == 1.0


def test_dedupe_keeps_first_and_reports_what_it_dropped():
    a = record("a", text="Ana: I'll call the vendor about the delayed shipment tomorrow morning.")
    b = record("b", text="ana: i'll call the vendor about the delayed shipment tomorrow morning!")
    c = record("c", text="Sam: I can update the roadmap slide once I get the final numbers.")
    kept, dropped = lab.dedupe([a, b, c])
    assert [r["id"] for r in kept] == ["a", "c"]
    assert dropped == [{"id": "b", "duplicate_of": "a", "jaccard": 1.0}]


def test_dedupe_finds_the_planted_duplicates(records):
    clean = [r for r in records if not lab.validate_record(r)]
    kept, dropped = lab.dedupe(clean)
    pairs = {(d["id"], d["duplicate_of"]) for d in dropped}
    assert pairs == {("e05-reexport", "e05"), ("t07-fwd", "t07"), ("m03-v2", "m03")}, pairs
    assert len(kept) == 44
    fwd = next(d for d in dropped if d["id"] == "t07-fwd")
    assert 0.7 <= fwd["jaccard"] < 1.0, "the forwarded ticket is a near-duplicate, not an exact one"


# ---------------------------------------------------------------- 3. splits


@pytest.fixture(scope="module")
def kept(records):
    clean = [r for r in records if not lab.validate_record(r)]
    return lab.dedupe(clean)[0]


def test_split_is_a_partition(kept):
    splits = lab.stratified_group_split(kept)
    assert set(splits) == {"train", "val", "test"}
    ids = [r["id"] for s in splits.values() for r in s]
    assert sorted(ids) == sorted(r["id"] for r in kept), "every record lands in exactly one split"


def test_split_is_deterministic_and_seeded(kept):
    a = lab.stratified_group_split(kept, seed=13)
    b = lab.stratified_group_split(kept, seed=13)
    c = lab.stratified_group_split(kept, seed=99)
    ids = lambda s: {k: [r["id"] for r in v] for k, v in s.items()}  # noqa: E731
    assert ids(a) == ids(b), "the same seed must give the same split"
    assert ids(a) != ids(c), "a different seed should give a different split"


def test_split_is_stratified_by_kind(kept):
    splits = lab.stratified_group_split(kept)
    for name in ("val", "test"):
        kinds = Counter(r["kind"] for r in splits[name])
        assert set(kinds) == {"email", "ticket", "meeting", "chat"}, f"{name} is missing a kind: {kinds}"
        assert all(v == 2 for v in kinds.values()), f"each kind should contribute 2 records to {name}: {kinds}"
    assert len(splits["train"]) == 28


def test_threads_never_cross_splits(kept):
    splits = lab.stratified_group_split(kept)
    where = {}
    for name, rs in splits.items():
        for r in rs:
            where.setdefault(r["thread"], set()).add(name)
    assert all(len(v) == 1 for v in where.values()), {k: v for k, v in where.items() if len(v) > 1}
    assert len(where["th-e08"]) == 1 and len(where["th-t10"]) == 1, "multi-message threads stay together"


def test_split_rejects_a_group_with_mixed_kinds():
    a = record("a")
    b = record("b", kind="email")
    b["thread"] = a["thread"]
    with pytest.raises(ValueError):
        lab.stratified_group_split([a, b])


def test_split_preserves_input_order_within_each_split(kept):
    splits = lab.stratified_group_split(kept)
    order = {r["id"]: i for i, r in enumerate(kept)}
    for rs in splits.values():
        positions = [order[r["id"]] for r in rs]
        assert positions == sorted(positions)


def test_leakage_check_finds_shared_threads_and_near_duplicates(by_id):
    train = [by_id["t07"], by_id["e08"]]
    test = [by_id["t07-fwd"], by_id["e09"], by_id["c02"]]
    found = lab.check_split_leakage({"train": train, "val": [], "test": test})
    got = {(p["a"], p["b"], p["reason"]) for p in found}
    assert got == {
        (("train", "t07"), ("test", "t07-fwd"), "near-duplicate"),
        (("train", "e08"), ("test", "e09"), "same group"),
    }, got


def test_clean_build_has_no_leakage(records):
    report = lab.build_dataset(records)
    assert report.leakage == []
    assert sorted(report.quarantined) == ["e12", "m12", "t12"]
    assert len(report.dropped) == 3


# ---------------------------------------------------------------- 4. chat format and the JSONL validator


def test_to_chat_example_shape(by_id):
    ex = lab.to_chat_example(by_id["m01"])
    assert set(ex) == {"messages"}, "no ids or metadata inside a training example"
    roles = [m["role"] for m in ex["messages"]]
    assert roles == ["system", "user", "assistant"]
    assert by_id["m01"]["text"] in ex["messages"][1]["content"]
    answer = json.loads(ex["messages"][2]["content"])
    assert answer == by_id["m01"]["label"]
    assert ex["messages"][2]["content"] == json.dumps(by_id["m01"]["label"], ensure_ascii=False, sort_keys=True)


def lines_for(*examples) -> list[str]:
    return [json.dumps(e) for e in examples]


@pytest.fixture
def good(by_id):
    return lab.to_chat_example(by_id["m01"])


def test_validator_accepts_good_lines(good, by_id):
    assert lab.validate_chat_lines(lines_for(good, lab.to_chat_example(by_id["c01"]))) == []


def test_validator_structural_problems(good):
    no_system = {"messages": good["messages"][1:]}
    ends_with_user = {"messages": good["messages"][:2]}
    wrong_order = {"messages": [good["messages"][0], good["messages"][2], good["messages"][1]]}
    late_system = {"messages": [good["messages"][1], good["messages"][0], good["messages"][2]]}
    bad_role = copy.deepcopy(good)
    bad_role["messages"][1]["role"] = "human"
    empty = copy.deepcopy(good)
    empty["messages"][1]["content"] = "   "
    lines = ["{not json"] + lines_for(no_system, ends_with_user, wrong_order, late_system, bad_role, empty, {"msgs": []})
    got = lab.validate_chat_lines(lines)
    assert got == [
        (1, "invalid JSON"),
        (3, "last message must be assistant"),
        (4, "roles must alternate user/assistant after an optional system message"),
        (5, "system message not first"),
        (6, "unknown role human"),
        (7, "empty content"),
        (8, "no messages list"),
    ], got
    assert not any(n == 2 for n, _ in got), "a system message is optional"


def test_validator_content_problems(good):
    bad_json = copy.deepcopy(good)
    bad_json["messages"][2]["content"] = "Here are the items: Priya sends the budget."
    leaked = copy.deepcopy(good)
    leaked["messages"][1]["content"] += "\n\nExample answer: " + good["messages"][2]["content"]
    long = copy.deepcopy(good)
    long["messages"][1]["content"] += " filler" * 3000
    got = lab.validate_chat_lines(lines_for(good, bad_json, leaked, long, good))
    assert (2, "assistant output fails schema") in got
    assert (3, "label leaked into prompt") in got
    assert any(n == 4 and p.startswith("too long (~") for n, p in got)
    assert (5, "duplicate of line 1") in got
    assert not any(n == 1 for n, _ in got)
    assert lab.validate_chat_lines(lines_for(long), max_tokens=10_000) == []


def test_fingerprint_is_order_independent_and_content_sensitive(by_id):
    a, b = by_id["e01"], by_id["t01"]
    assert lab.fingerprint([a, b]) == lab.fingerprint([b, a])
    assert len(lab.fingerprint([a])) == 64
    edited = copy.deepcopy(a)
    edited["label"]["items"][0]["priority"] = "low"
    assert lab.fingerprint([edited, b]) != lab.fingerprint([a, b]), "editing a test label must change the fingerprint"


def test_written_files_pass_the_validator(records, tmp_path):
    report = lab.build_dataset(records)
    lab.write_outputs(report, tmp_path)
    for split in ("train", "val"):
        lines = (tmp_path / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == len(report.splits[split])
        assert lab.validate_chat_lines(lines) == []
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["test_fingerprint"] == lab.fingerprint(report.splits["test"])
    test_ids = set(manifest["splits"]["test"])
    train_text = (tmp_path / "train.jsonl").read_text(encoding="utf-8")
    for rid in test_ids:
        text = next(r["text"] for r in records if r["id"] == rid)
        assert json.dumps(text)[1:-1] not in train_text, f"test document {rid} appears in train.jsonl"


# ---------------------------------------------------------------- 5. drafting labels (fake client)


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def fake_client(parsed, stop_reason="end_turn"):
    return SimpleNamespace(messages=FakeMessages(SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed)))


def test_draft_label_marks_output_for_review():
    src = {"id": "u9", "kind": "meeting", "thread": "th-u9", "text": "Mads: I'll pull the conversion data by Friday."}
    parsed = lab.Extraction.model_validate({"items": [item(
        task="Pull the conversion data", owner="Mads", evidence="I'll pull the conversion data by Friday.")]})
    client = fake_client(parsed)
    drafted = lab.draft_label(client, src)
    call = client.messages.calls[0]
    assert call["output_format"] is lab.Extraction
    assert src["text"] in call["messages"][0]["content"]
    assert not {"temperature", "top_p", "top_k"} & set(call), "sampling parameters are rejected on the current API"
    assert drafted["label_status"] == "needs_review"
    assert drafted["drafted_by"] == lab.MODEL
    assert drafted["draft_flags"] == []
    assert "label_status" not in src, "do not mutate the input record"
    assert lab.validate_record(drafted) == ["label not reviewed"], "drafts must never pass as gold"


def test_draft_label_flags_an_invented_quote():
    src = {"id": "u9", "kind": "meeting", "thread": "th-u9", "text": "Mads: I'll pull the conversion data by Friday."}
    parsed = lab.Extraction.model_validate({"items": [item(
        task="Pull the data", owner="Mads", evidence="Mads will pull the conversion numbers on Friday.")]})
    drafted = lab.draft_label(fake_client(parsed), src)
    assert drafted["draft_flags"] == ["item 0: evidence not found in source"]


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_draft_label_fails_loudly(stop):
    src = {"id": "u9", "kind": "chat", "thread": "th", "text": "Hi"}
    with pytest.raises(lab.DraftFailed):
        lab.draft_label(fake_client(lab.Extraction(items=[]), stop_reason=stop), src)


# ---------------------------------------------------------------- live


@pytest.mark.live
def test_live_draft_labels_for_review():
    import anthropic

    client = anthropic.Anthropic()
    unlabeled = lab.load_jsonl(DATA / "unlabeled.jsonl")
    for r in unlabeled:
        drafted = lab.draft_label(client, r)
        assert drafted["label_status"] == "needs_review"
        print(f"\n{r['id']} flags={drafted['draft_flags']}")
        for it in drafted["label"]["items"]:
            print(f"  - {it['task']} | owner={it['owner']} | due={it['due_phrase']} | {it['evidence']!r}")
