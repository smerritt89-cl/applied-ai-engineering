"""Lab 04 (Studio 2): cited answers you can check. Your file: fill in the TODOs.

Pipeline:
    question + retrieved passages
        -> Claude with each passage as a search_result block, citations enabled
        -> parse the response into claims, each with its citations
        -> verify offline: every citation points at a passage you provided,
           and every quoted span appears verbatim in that passage
"""
from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field

import anthropic

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
LAB_DIR = pathlib.Path(__file__).parent
PASSAGES_PATH = LAB_DIR / "passages.json"

ABSTAIN_PHRASE = "I don't know based on the provided sources."

SYSTEM_PROMPT = f"""You answer employee questions using only the search results provided in the user's message.

Rules:
- Use only facts stated in the search results. Do not add facts from general knowledge.
- Support every factual statement with the search result it came from.
- If sources disagree, prefer the most recent policy and say that an older source disagrees.
- If the search results do not contain the answer, reply with exactly: {ABSTAIN_PHRASE}
- Keep the answer short: two to four sentences."""

# Uncited text with at least this many words, or containing a digit, is worth a reviewer's look.
SUBSTANTIVE_WORDS = 10
_DIGIT = re.compile(r"\d")


# ---------------------------------------------------------------- data


@dataclass
class Passage:
    id: str
    title: str
    text: str


@dataclass
class Citation:
    passage_id: str
    quote: str
    search_result_index: int | None = None


@dataclass
class Claim:
    text: str
    citations: list[Citation] = field(default_factory=list)


@dataclass
class CitedAnswer:
    claims: list[Claim]
    stop_reason: str | None = None

    @property
    def text(self) -> str:
        return "".join(c.text for c in self.claims)


@dataclass
class Problem:
    claim_index: int
    kind: str  # "unknown passage" | "index mismatch" | "quote not in passage"
    detail: str


@dataclass
class Report:
    problems: list[Problem]
    uncited: list[int]  # claim indices with substantive text and no citation (warnings)
    abstained: bool
    cited_claims: int

    @property
    def ok(self) -> bool:
        return not self.problems


def load_passages(path: pathlib.Path = PASSAGES_PATH) -> list[Passage]:
    data = json.loads(pathlib.Path(path).read_text())
    return [Passage(**p) for p in data["passages"]]


# ---------------------------------------------------------------- request


def build_search_results(passages: list[Passage]) -> list[dict]:
    """One search_result block per passage. `source` carries the passage id, so citations name it."""
    # TODO: return one dict per passage with keys type ("search_result"), source (the passage id),
    # title, content (a list with one {"type": "text", "text": ...} block), and citations ({"enabled": True}).
    raise NotImplementedError("TODO")


def build_messages(question: str, passages: list[Passage]) -> list[dict]:
    """Sources first, question last, in a single user turn. No assistant prefill."""
    # TODO: one user message whose content is every search result, then the question as a text block.
    raise NotImplementedError("TODO")


# ---------------------------------------------------------------- parsing


def _get(obj, key, default=None):
    """Read a field from an SDK object or a plain dict (fixtures and logs are dicts)."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def parse_claude_response(response) -> CitedAnswer:
    """Turn a Messages API response into claims.

    Each `text` block becomes one Claim. Its `search_result_location` citations become
    Citation(passage_id=source, quote=cited_text, search_result_index=...). Skip every
    non-text block (for example `thinking`), and ignore other citation types.
    """
    # TODO: loop over the response's content with _get(...), so this works for SDK objects and dicts.
    raise NotImplementedError("TODO")


_MARKER = re.compile(r'\[(?P<id>[A-Za-z0-9_-]+):\s*"(?P<quote>[^"]*)"\]')


def parse_marked_answer(text: str) -> CitedAnswer:
    """Parse a prompt-based citation format, usable with any provider.

    Each non-empty line is one claim. Markers look like [travel-002: "exact quote"].
    The claim text is the line with markers removed and whitespace collapsed.
    """
    # TODO: use _MARKER.finditer(line) for citations and _MARKER.sub("", line) for the claim text.
    raise NotImplementedError("TODO")


# ---------------------------------------------------------------- verification


def normalize(text: str) -> str:
    """Collapse every run of whitespace into one space and strip the ends."""
    raise NotImplementedError("TODO")


def is_substantive(text: str) -> bool:
    words = text.split()
    return len(words) >= SUBSTANTIVE_WORDS or bool(_DIGIT.search(text))


def verify_answer(answer: CitedAnswer, passages: list[Passage]) -> Report:
    """Check every citation against the passages you sent.

    Problems, per citation, in this order (at most one per citation):
      "unknown passage"       passage_id is not one of the provided passages
      "index mismatch"        search_result_index is set and passages[index].id != passage_id
      "quote not in passage"  normalized quote is empty, or not a substring of the normalized passage text
    Warnings: indices of claims with no citations whose text is substantive (is_substantive).
    abstained: the answer contains ABSTAIN_PHRASE and has no citations at all.
    cited_claims: number of claims with at least one citation and no problems.
    """
    # TODO: build a dict of passages by id, then check each citation of each claim (use is_substantive).
    raise NotImplementedError("TODO")


# ---------------------------------------------------------------- the call


class AnswerFailed(Exception):
    """Raised when no usable answer came back."""


def answer_with_citations(client, question: str, passages: list[Passage], model: str = MODEL) -> CitedAnswer:
    """One Messages API call with the passages as search results and citations enabled.

    Raises AnswerFailed for stop_reason "refusal" or "max_tokens". Do not send
    output_config.format (structured outputs are incompatible with citations) or
    sampling parameters (rejected on the current API version).
    """
    # TODO: call client.messages.create(model=model, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT,
    # messages=build_messages(question, passages)), check stop_reason, then return parse_claude_response(response).
    raise NotImplementedError("TODO")


def print_answer(answer: CitedAnswer, report: Report) -> None:
    for i, claim in enumerate(answer.claims):
        tags = ", ".join(c.passage_id for c in claim.citations)
        flag = " [UNCITED]" if i in report.uncited else ""
        print(f"{claim.text}{f' [{tags}]' if tags else ''}{flag}", end="")
    print()
    for p in report.problems:
        print(f"  PROBLEM claim {p.claim_index}: {p.kind} ({p.detail})")
    print(f"  ok={report.ok} abstained={report.abstained} cited_claims={report.cited_claims}")


def main() -> None:
    client = anthropic.Anthropic()
    passages = load_passages()
    for question in [
        "Can I expense a hotel room upgrade?",
        "I have a 5-hour flight next month. Can I book business class?",
        "What is the per diem for international travel in Japan?",
    ]:
        print(f"\nQ: {question}")
        answer = answer_with_citations(client, question, passages)
        print_answer(answer, verify_answer(answer, passages))


if __name__ == "__main__":
    main()
