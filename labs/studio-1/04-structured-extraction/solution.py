"""Lab 04: structured extraction you can check (reference solution).

Pipeline:
    document -> Claude with structured outputs (messages.parse + Pydantic)
             -> on a validation error, retry once with the error fed back
             -> verify every evidence quote against the document
             -> return the items plus flags for anything unsupported
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import anthropic
import pydantic
from pydantic import BaseModel, ConfigDict, Field, model_validator

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
SAMPLES_DIR = pathlib.Path(__file__).parent / "samples"

SYSTEM_PROMPT = """You extract action items from business documents such as emails, support tickets, and meeting notes.
An action item is a commitment someone made, or a request that someone do something.

Rules:
- Include only items the document states. Do not invent tasks, owners, or dates.
- evidence must be copied word for word from the document as one contiguous span. Do not paraphrase, shorten words, or fix typos.
- If no specific person is responsible, set owner to null and explain why in owner_missing_reason.
- Set due_date only when the document gives a specific calendar date. Copy any deadline wording, such as "by Thursday", into due_phrase.
- If the document has no action items, return an empty list."""


# ---------------------------------------------------------------- models


class ActionItem(BaseModel):
    """One commitment or request found in a document."""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=3, description="What will be done, as a short imperative phrase")
    owner: str | None = Field(
        description="Name of the person responsible, as written in the document; null if no specific person is named"
    )
    owner_missing_reason: str | None = Field(
        description="If owner is null, a few words on why (for example 'addressed to a team'); otherwise null"
    )
    due_date: date | None = Field(
        description="Deadline as an ISO date, only if the document states a specific calendar date; otherwise null"
    )
    due_phrase: str | None = Field(
        description="The deadline wording copied from the document (for example 'by end of day Thursday'), or null"
    )
    priority: Literal["high", "medium", "low"] = Field(
        description="high if the document signals urgency or a near deadline, low if optional, otherwise medium"
    )
    evidence: str = Field(
        min_length=10,
        description="A verbatim quote from the document, copied exactly, that shows this commitment or request",
    )

    @model_validator(mode="after")
    def _owner_or_reason(self) -> "ActionItem":
        if self.owner is None and not (self.owner_missing_reason or "").strip():
            raise ValueError("owner_missing_reason is required when owner is null")
        return self


class Extraction(BaseModel):
    """Everything extracted from one document."""

    model_config = ConfigDict(extra="forbid")

    items: list[ActionItem] = Field(description="Every action item in the document; an empty list if there are none")


# ---------------------------------------------------------------- verification


@dataclass
class Flag:
    index: int
    task: str
    problems: list[str]


def normalize(text: str) -> str:
    """Collapse every run of whitespace into one space and strip the ends."""
    return " ".join(text.split())


def verify_evidence(extraction: Extraction, source: str) -> list[Flag]:
    """Flag items whose evidence or owner is not supported by the source text.

    Problems, in order:
      "evidence not found in source"  normalized evidence is empty or not a substring of the normalized source
      "owner not found in source"     owner is set but the name does not appear anywhere in the source
    """
    text = normalize(source)
    flags: list[Flag] = []
    for i, item in enumerate(extraction.items):
        problems = []
        quote = normalize(item.evidence)
        if not quote or quote not in text:
            problems.append("evidence not found in source")
        if item.owner is not None and normalize(item.owner) not in text:
            problems.append("owner not found in source")
        if problems:
            flags.append(Flag(index=i, task=item.task, problems=problems))
    return flags


# ---------------------------------------------------------------- the API call


class ExtractionFailed(Exception):
    """Raised when no trustworthy extraction could be produced."""


@dataclass
class ExtractionResult:
    extraction: Extraction
    flags: list[Flag] = field(default_factory=list)
    attempts: int = 1


def build_messages(document: str) -> list[dict]:
    """One user turn holding the document. No assistant prefill: it is rejected on current models."""
    return [
        {
            "role": "user",
            "content": f"<document>\n{document}\n</document>\n\nExtract the action items from this document.",
        }
    ]


def format_errors(err: pydantic.ValidationError) -> str:
    """One line per problem: '<loc>: <msg>', with '(root)' for an empty loc."""
    lines = []
    for e in err.errors():
        where = ".".join(str(p) for p in e["loc"]) or "(root)"
        lines.append(f"{where}: {e['msg']}")
    return "\n".join(lines)


def retry_message(err: pydantic.ValidationError) -> dict:
    return {
        "role": "user",
        "content": (
            "A previous attempt at this extraction failed validation with these errors:\n"
            f"{format_errors(err)}\n\n"
            "Extract the action items again and make sure the output satisfies every rule."
        ),
    }


def extract(client, document: str, model: str = MODEL) -> ExtractionResult:
    """Extract action items with structured outputs, retrying once on a validation error.

    - Uses client.messages.parse(..., output_format=Extraction). The SDK sends the
      schema as output_config.format and validates the reply against the original
      Pydantic model, including constraints the API schema can't express.
    - A ValidationError with type 'json_invalid' means the JSON itself is broken,
      which under constrained decoding points to truncation (max_tokens) or a
      refusal. Retrying the same request won't help, so fail instead.
    - Any other ValidationError is retried exactly once, with the errors fed back.
    - Checks stop_reason before trusting parsed_output.
    """
    messages = build_messages(document)
    for attempt in (1, 2):
        try:
            response = client.messages.parse(
                model=model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=messages,
                output_format=Extraction,
            )
        except pydantic.ValidationError as err:
            if any(e["type"] == "json_invalid" for e in err.errors()):
                raise ExtractionFailed(
                    "reply was not valid JSON (likely truncated at max_tokens, or a refusal)"
                ) from err
            if attempt == 2:
                raise ExtractionFailed(f"output still invalid after a retry:\n{format_errors(err)}") from err
            messages = messages + [retry_message(err)]
            continue

        if response.stop_reason == "refusal":
            raise ExtractionFailed("the model declined this request (stop_reason=refusal)")
        if response.stop_reason == "max_tokens":
            raise ExtractionFailed("output was truncated (stop_reason=max_tokens); raise max_tokens or split the input")
        extraction = response.parsed_output
        if extraction is None:
            raise ExtractionFailed("no parsed output in the response")
        return ExtractionResult(extraction=extraction, flags=verify_evidence(extraction, document), attempts=attempt)

    raise ExtractionFailed("unreachable")  # the loop always returns or raises


def main() -> None:
    client = anthropic.Anthropic()
    for path in sorted(SAMPLES_DIR.glob("*.txt")):
        document = path.read_text()
        result = extract(client, document)
        print(f"\n== {path.name} ({len(result.extraction.items)} items, {result.attempts} attempt(s))")
        flagged = {f.index: f.problems for f in result.flags}
        for i, item in enumerate(result.extraction.items):
            status = "FLAG " + ", ".join(flagged[i]) if i in flagged else "ok"
            owner = item.owner or f"(none: {item.owner_missing_reason})"
            print(f"[{status}] {item.task} | owner={owner} | due={item.due_date or item.due_phrase}")
            print(f'        evidence: "{item.evidence}"')


if __name__ == "__main__":
    main()
