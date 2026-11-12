"""Regenerate the frozen test set and recorded predictions in this folder (deterministic).

Everything here is SYNTHETIC. The test set stands in for a frozen, labeled set of meeting
snippets (the Studio 1 action-item task, reduced to one candidate item per snippet). The
three prediction files stand in for recorded runs of:

  ft-lora   a small open model with a LoRA adapter, served on your own GPU
  base      the same small model without the adapter (same serving setup)
  frontier  a frontier model called through a provider API

The error rates below are invented to make the analysis interesting. They are not
measurements of any real model. Run from the lab folder:

    python fixtures/make_fixtures.py
"""
import hashlib
import json
import math
import pathlib
import random

HERE = pathlib.Path(__file__).parent
rng = random.Random(5404)

MEETING_DATE = "2026-11-09"  # a Monday
ATTENDEES = ["Priya", "Sam", "Lee", "Ana", "Marcus", "Dana"]
TASKS = [
    "send the revised budget to finance",
    "update the roadmap slide",
    "book the offsite venue",
    "call the vendor about the delayed shipment",
    "draft the launch email",
    "review the security questionnaire",
    "share the interview scorecards",
    "fix the onboarding checklist",
    "confirm the launch date with marketing",
    "write up the incident timeline",
    "renew the analytics contract",
    "clean up the backlog labels",
]
# phrase -> resolved date relative to MEETING_DATE (resolution is deterministic code, not the model's job)
DUE = [
    ("by Friday", "2026-11-13"),
    ("tomorrow", "2026-11-10"),
    ("by next Tuesday", "2026-11-17"),
    ("by November 20", "2026-11-20"),
    ("by the end of the month", "2026-11-30"),
    (None, None),
    (None, None),
]
HIGH = ["The client is waiting on this, so", "This is blocking the release:", "Urgent one:"]
LOW = ["No rush, but", "When there's time,", "Nice to have:"]
NON_ACTION = [
    "{who}: Someone should probably {task} at some point.",
    "{who}: We talked about whether to {task}, but nobody has decided.",
    "{who}: Last quarter we tried to {task} and it went fine.",
    "{who}: It would be great if the team could {task}, in theory.",
]


def make_case(i):
    who = rng.choice(ATTENDEES)
    task = rng.choice(TASKS)
    if rng.random() < 0.2:
        text = rng.choice(NON_ACTION).format(who=who, task=task)
        gold = {"is_action_item": False, "owner": None, "due_date": None, "priority": None}
    else:
        phrase, date = rng.choice(DUE)
        r = rng.random()
        if r < 0.25:
            lead, priority = rng.choice(HIGH), "high"
        elif r < 0.45:
            lead, priority = rng.choice(LOW), "low"
        else:
            lead, priority = "", "medium"
        when = f" {phrase}" if phrase else ""
        text = f"{who}: {lead + ' ' if lead else ''}I'll {task}{when}.".replace("  ", " ")
        gold = {"is_action_item": True, "owner": who, "due_date": date, "priority": priority}
    return {"id": f"t{i:03d}", "meeting_date": MEETING_DATE, "text": text, "gold": gold}


cases = [make_case(i) for i in range(1, 151)]

# Corrupt individual fields the way models actually get them wrong.
def shift_date(d):
    y, m, day = (int(x) for x in d.split("-"))
    delta = rng.choice([-1, 1, 7])
    # simple day arithmetic within November 2026 is enough for this fixture
    day = min(30, max(1, day + delta))
    return f"{y:04d}-{m:02d}-{day:02d}"


def predict(gold, rates):
    if rng.random() < rates["parse"]:
        return None  # unparseable or schema-invalid output
    out = dict(gold)
    if rng.random() < rates["is_action_item"]:
        out["is_action_item"] = not gold["is_action_item"]
        if out["is_action_item"]:  # invented an item
            out["owner"] = rng.choice(ATTENDEES)
            out["due_date"] = None
            out["priority"] = "medium"
        else:  # missed a real item
            out.update(owner=None, due_date=None, priority=None)
        return out
    if not gold["is_action_item"]:
        return out
    if rng.random() < rates["owner"]:
        out["owner"] = rng.choice([a for a in ATTENDEES if a != gold["owner"]] + [None])
    elif rng.random() < 0.15:
        out["owner"] = gold["owner"].lower() + " "  # harmless formatting noise: normalization should accept it
    if rng.random() < rates["due_date"]:
        out["due_date"] = shift_date(gold["due_date"]) if gold["due_date"] else rng.choice(["2026-11-13", "2026-11-10"])
    if rng.random() < rates["priority"]:
        out["priority"] = rng.choice([p for p in ("low", "medium", "high") if p != gold["priority"]])
    return out


def lognormal(median, spread):
    return round(median * math.exp(rng.gauss(0, spread)), 3)


SYSTEMS = {
    "ft-lora": {
        "model": "open-3b-instruct + action-items-lora-v1 (synthetic)",
        "prompt_version": "ft-train-format-v1",
        "serving": "vLLM on 1x NVIDIA L4, batch traffic",
        "rates": {"parse": 0.007, "is_action_item": 0.03, "owner": 0.04, "due_date": 0.06, "priority": 0.08},
        "latency": (0.45, 0.35),
        "tokens_in": (140, 25),
        "tokens_out": (45, 8),
    },
    "base": {
        "model": "open-3b-instruct, no adapter (synthetic)",
        "prompt_version": "zero-shot-instructions-v2",
        "serving": "vLLM on 1x NVIDIA L4, batch traffic",
        "rates": {"parse": 0.10, "is_action_item": 0.10, "owner": 0.12, "due_date": 0.25, "priority": 0.40},
        "latency": (0.55, 0.35),
        "tokens_in": (430, 30),
        "tokens_out": (60, 15),
    },
    "frontier": {
        "model": "frontier-api-model (synthetic)",
        "prompt_version": "few-shot-instructions-v4",
        "serving": "provider API",
        "rates": {"parse": 0.0, "is_action_item": 0.04, "owner": 0.03, "due_date": 0.09, "priority": 0.25},
        "latency": (1.6, 0.30),
        "tokens_in": (620, 40),
        "tokens_out": (70, 12),
    },
}


def fingerprint(test_cases):
    """Same definition as starter.fingerprint: sha256 of ids, inputs, and gold labels."""
    payload = json.dumps([[c["id"], c["text"], c["gold"]] for c in test_cases], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


fp = fingerprint(cases)
(HERE / "test_set.jsonl").write_text("".join(json.dumps(c) + "\n" for c in cases))

for name, spec in SYSTEMS.items():
    preds = []
    for c in cases:
        preds.append({
            "id": c["id"],
            "output": predict(c["gold"], spec["rates"]),
            "latency_s": lognormal(*spec["latency"]),
            "input_tokens": max(1, int(rng.gauss(*spec["tokens_in"]))),
            "output_tokens": max(1, int(rng.gauss(*spec["tokens_out"]))),
        })
    run = {
        "system": name,
        "model": spec["model"],
        "prompt_version": spec["prompt_version"],
        "serving": spec["serving"],
        "test_set": "action-items-frozen-v1",
        "test_set_sha256": fp,
        "notes": "Synthetic predictions for a lab exercise. Not a measurement of any real model.",
        "predictions": preds,
    }
    (HERE / f"{name}.json").write_text(json.dumps(run, indent=1) + "\n")

# A run scored against a different version of the test set: the lab must refuse it.
stale = json.loads((HERE / "ft-lora.json").read_text())
stale["test_set"] = "action-items-frozen-v0"
stale["test_set_sha256"] = "0" * 64
(HERE / "ft-lora-stale.json").write_text(json.dumps(stale, indent=1) + "\n")

costs = {
    "_note": (
        "Prices are snapshots for the exercise (2026-11-11). The API row uses Claude Sonnet 5.5 list prices; "
        "the GPU row uses the Hugging Face Inference Endpoints list price for 1x NVIDIA L4 on AWS. "
        "tasks_per_hour is a measured throughput at the batch size you serve with; utilization is the share "
        "of paid GPU hours doing useful work. Check current pricing pages before reusing any number."
    ),
    "ft-lora": {"kind": "selfhost", "gpu_hourly_usd": 0.80, "tasks_per_hour": 3000, "utilization": 0.2},
    "base": {"kind": "selfhost", "gpu_hourly_usd": 0.80, "tasks_per_hour": 2600, "utilization": 0.2},
    "frontier": {"kind": "api", "usd_per_mtok_in": 2.00, "usd_per_mtok_out": 10.00},
}
(HERE / "costs.json").write_text(json.dumps(costs, indent=1) + "\n")
print(f"wrote {len(cases)} cases, fingerprint {fp[:12]}")
