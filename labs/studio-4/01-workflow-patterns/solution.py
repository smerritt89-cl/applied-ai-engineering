"""Lab 01 (Studio 4): workflow patterns for a PM task. Reference solution.

Pipeline (every step is chosen by code, so this is a workflow, not an agent):

    request --ROUTING--> audience (exec | team | client), with a safe fallback
    notes   --CHAINING--> extract facts with quotes -> GATE (code) -> verified facts
    facts   --EVALUATOR-OPTIMIZER--> draft -> code checks -> model rubric -> revise (max rounds)
            -> status update, approved or flagged for a person
"""
from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field

MODEL = "claude-opus-5-5"  # drafting
ROUTER_MODEL = "claude-haiku-5-5"  # cheap, fast classification
EVALUATOR_MODEL = "claude-sonnet-5-5"  # a different model from the drafter, for the rubric review
MAX_TOKENS = 16000
SAMPLES_DIR = pathlib.Path(__file__).parent / "samples"

FALLBACK_AUDIENCE = "team"  # internal, so a misroute never sends internal detail outside

AUDIENCES = {
    "exec": {
        "max_words": 120,
        "include_risks": True,
        "instructions": "Write for executives: the headline first, then decisions, date changes, and top risks. No detail they cannot act on.",
    },
    "team": {
        "max_words": 300,
        "include_risks": True,
        "instructions": "Write for the project team: every decision, every action item with its owner and due date, and every risk.",
    },
    "client": {
        "max_words": 200,
        "include_risks": False,
        "instructions": "Write for the client: decisions and dates that affect them, in a calm, external-safe tone. Never mention internal matters.",
    },
}

ROUTER_SYSTEM = """You classify requests for project status updates by audience.
Reply with exactly one word: exec, team, or client.
exec = for executives or leadership. team = for the internal project team. client = for the external customer."""

EXTRACT_SYSTEM = """You extract facts from meeting notes for a status update.
Rules:
- Include only what the notes state. Do not invent items, owners, or dates.
- quote must be copied word for word from the notes, as one contiguous span.
- owner is the named person responsible, or null if nobody is named."""

DRAFT_SYSTEM = """You write concise, accurate project status updates from verified facts.
Use only the facts you are given. Name the owner of every action item you mention."""

REVIEW_SYSTEM = """You review project status updates against a rubric. Be strict.
Fail the draft if it states anything the facts do not support, buries a risk, or is unclear about who does what."""

FACTS_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "text", "owner", "quote"],
                    "properties": {
                        "kind": {"type": "string", "enum": ["decision", "action", "risk", "update"]},
                        "text": {"type": "string"},
                        "owner": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "quote": {"type": "string"},
                    },
                },
            }
        },
    },
}

VERDICT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["pass", "problems"],
        "properties": {"pass": {"type": "boolean"}, "problems": {"type": "array", "items": {"type": "string"}}},
    },
}


class StepFailed(Exception):
    """A model call ended without a usable answer (refusal, truncation, no text)."""


class GateFailed(Exception):
    """The chain's gate rejected the extraction, so nothing was drafted."""


# ---------------------------------------------------------------- 1. one model call


def text_of(response) -> str:
    """Return the text of a Messages API response, or raise StepFailed.

    Check stop_reason first: "refusal" and "max_tokens" mean the answer is unusable.
    Current models may return thinking blocks before the text, so take the first block
    whose type is "text".
    """
    if response.stop_reason in ("refusal", "max_tokens"):
        raise StepFailed(f"model stopped early: stop_reason={response.stop_reason}")
    for block in response.content:
        if block.type == "text":
            return block.text
    raise StepFailed("response contained no text block")


def call(client, *, model: str, system: str, prompt: str, effort: str = "medium", schema: dict | None = None) -> str:
    """Make one Messages API call and return its text.

    - One user message holding the prompt (no assistant prefill; current models reject it).
    - output_config always carries the effort; add "format": schema when a schema is given.
    - Never send temperature, top_p, or top_k (rejected on the current API).
    """
    output_config: dict = {"effort": effort}
    if schema is not None:
        output_config["format"] = schema
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system,
        output_config=output_config,
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(response)


# ---------------------------------------------------------------- 2. routing


@dataclass
class Route:
    audience: str
    raw: str
    fell_back: bool


def parse_audience(raw: str) -> str | None:
    """Strip whitespace and trailing periods, lowercase, and return a key of AUDIENCES, or None."""
    label = raw.strip().rstrip(".").strip().lower()
    return label if label in AUDIENCES else None


def route_audience(client, request: str) -> Route:
    """Classify the request with ROUTER_MODEL at effort "low".

    An unparseable reply falls back to FALLBACK_AUDIENCE with fell_back=True,
    so you can count how often the router is confused.
    """
    raw = call(client, model=ROUTER_MODEL, system=ROUTER_SYSTEM, prompt=request, effort="low")
    audience = parse_audience(raw)
    if audience is None:
        return Route(audience=FALLBACK_AUDIENCE, raw=raw, fell_back=True)
    return Route(audience=audience, raw=raw, fell_back=False)


# ---------------------------------------------------------------- 3. chaining with a gate


def normalize(text: str) -> str:
    """Collapse runs of whitespace to one space and strip the ends."""
    return re.sub(r"\s+", " ", text).strip()


def extract_facts(client, notes: str) -> list[dict]:
    """Chain step 1: structured extraction with FACTS_SCHEMA. Returns the list of items."""
    prompt = f"<notes>\n{notes}\n</notes>\n\nList every decision, action item, risk, and progress update in these notes."
    raw = call(client, model=MODEL, system=EXTRACT_SYSTEM, prompt=prompt, schema=FACTS_SCHEMA)
    return json.loads(raw)["items"]


@dataclass
class GateResult:
    kept: list[dict]
    rejected: list[tuple[dict, str]]  # (item, reason)


def gate_facts(items: list[dict], notes: str) -> GateResult:
    """Chain gate (pure code). Reject an item when:
    - its quote is empty after normalization ("empty quote")
    - its normalized quote is not a substring of the normalized notes ("quote not in notes")
    - it names an owner who does not appear in the notes ("owner not in notes")
    Check in that order and record the first reason only.
    """
    text = normalize(notes)
    kept, rejected = [], []
    for item in items:
        quote = normalize(item.get("quote") or "")
        owner = item.get("owner")
        if not quote:
            rejected.append((item, "empty quote"))
        elif quote not in text:
            rejected.append((item, "quote not in notes"))
        elif owner is not None and normalize(owner) not in text:
            rejected.append((item, "owner not in notes"))
        else:
            kept.append(item)
    return GateResult(kept=kept, rejected=rejected)


def facts_for(audience: str, facts: list[dict]) -> list[dict]:
    """Drop risks for audiences whose config has include_risks False."""
    if AUDIENCES[audience]["include_risks"]:
        return list(facts)
    return [f for f in facts if f["kind"] != "risk"]


def draft_update(client, facts: list[dict], audience: str, feedback: str = "") -> str:
    """Chain step 2: draft from verified facts only (never from the raw notes)."""
    cfg = AUDIENCES[audience]
    prompt = (
        f"{cfg['instructions']}\nUse at most {cfg['max_words']} words.\n\n"
        f"<facts>\n{json.dumps(facts, indent=2)}\n</facts>"
    )
    if feedback:
        prompt += f"\n\n<feedback>\n{feedback}\n</feedback>"
    return call(client, model=MODEL, system=DRAFT_SYSTEM, prompt=prompt)


# ---------------------------------------------------------------- 4. evaluator-optimizer


def code_checks(draft: str, facts: list[dict], audience: str, confidential_terms: tuple[str, ...] = ()) -> list[str]:
    """Deterministic checks, run before any model review. Return a list of problems.
    - "draft is empty" if there is no text
    - "too long: N words (limit M)" if over the audience's max_words (words = whitespace-split tokens)
    - "missing owner: NAME" for each action fact (in facts_for(audience, facts)) whose owner is not in the draft
    - "confidential term: TERM" for each term found in a client draft (case-insensitive)
    """
    problems = []
    if not draft.strip():
        return ["draft is empty"]
    words = len(draft.split())
    limit = AUDIENCES[audience]["max_words"]
    if words > limit:
        problems.append(f"too long: {words} words (limit {limit})")
    for fact in facts_for(audience, facts):
        owner = fact.get("owner")
        if fact["kind"] == "action" and owner and owner not in draft:
            problems.append(f"missing owner: {owner}")
    if audience == "client":
        lowered = draft.lower()
        problems += [f"confidential term: {t}" for t in confidential_terms if t.lower() in lowered]
    return problems


def model_review(client, draft: str, facts: list[dict], audience: str) -> list[str]:
    """Rubric review with EVALUATOR_MODEL and VERDICT_SCHEMA. Return its problems.
    If it says pass is False but lists no problems, return ["reviewer rejected the draft without reasons"].
    If it says pass is True, return []."""
    prompt = (
        f"Audience: {audience}\n\n<facts>\n{json.dumps(facts, indent=2)}\n</facts>\n\n"
        f"<draft>\n{draft}\n</draft>\n\n"
        "Does the draft pass? List each specific problem."
    )
    verdict = json.loads(call(client, model=EVALUATOR_MODEL, system=REVIEW_SYSTEM, prompt=prompt, schema=VERDICT_SCHEMA))
    if verdict["pass"]:
        return []
    return verdict["problems"] or ["reviewer rejected the draft without reasons"]


@dataclass
class RefineResult:
    draft: str
    approved: bool
    rounds: int
    history: list[list[str]] = field(default_factory=list)  # problems found in each round


def refine(client, facts: list[dict], audience: str, confidential_terms: tuple[str, ...] = (), max_rounds: int = 3) -> RefineResult:
    """Draft, check, revise. Each round:
    1. draft_update with the previous round's feedback (empty on round 1)
    2. code_checks; only if they pass, model_review (do not pay for a review of a draft code already rejected)
    3. no problems -> return approved
    4. otherwise feedback = "Fix these problems in your next draft:\n- " + "\n- ".join(problems)
    After max_rounds, return the last draft with approved=False, for a person to review.
    """
    audience_facts = facts_for(audience, facts)
    feedback, draft, history = "", "", []
    for round_no in range(1, max_rounds + 1):
        draft = draft_update(client, audience_facts, audience, feedback)
        problems = code_checks(draft, facts, audience, confidential_terms)
        if not problems:
            problems = model_review(client, draft, audience_facts, audience)
        history.append(problems)
        if not problems:
            return RefineResult(draft=draft, approved=True, rounds=round_no, history=history)
        feedback = "Fix these problems in your next draft:\n- " + "\n- ".join(problems)
    return RefineResult(draft=draft, approved=False, rounds=max_rounds, history=history)


# ---------------------------------------------------------------- 5. the whole workflow


@dataclass
class StatusUpdate:
    route: Route
    gate: GateResult
    result: RefineResult


def status_update(client, notes: str, request: str, confidential_terms: tuple[str, ...] = (), max_rounds: int = 3) -> StatusUpdate:
    """Route, extract, gate, then refine. Raise GateFailed (before any drafting) if the gate keeps nothing."""
    route = route_audience(client, request)
    gate = gate_facts(extract_facts(client, notes), notes)
    if not gate.kept:
        raise GateFailed(f"no supported facts; rejected: {[reason for _, reason in gate.rejected]}")
    result = refine(client, gate.kept, route.audience, confidential_terms, max_rounds)
    return StatusUpdate(route=route, gate=gate, result=result)


if __name__ == "__main__":
    import anthropic

    notes = (SAMPLES_DIR / "weekly-sync.md").read_text()
    out = status_update(
        anthropic.Anthropic(),
        notes,
        "Can you send the client a quick note on where the portal relaunch stands?",
        confidential_terms=("Bluebird", "margin"),
    )
    print(f"Audience: {out.route.audience} (router said {out.route.raw!r}, fell back: {out.route.fell_back})")
    print(f"Gate kept {len(out.gate.kept)} facts, rejected {len(out.gate.rejected)}: {[r for _, r in out.gate.rejected]}")
    print(f"Approved: {out.result.approved} after {out.result.rounds} round(s); problems per round: {out.result.history}\n")
    print(out.result.draft)
