"""Lab 04: structured extraction you can check (your file: fill in the TODOs).

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
    """One commitment or request found in a document.

    TODO: define these fields. Every field is REQUIRED (no defaults) and every
    field gets a Field(description=...) written as an instruction to the model.
      task                  str, at least 3 characters
      owner                 str or None (null when no specific person is named)
      owner_missing_reason  str or None (why owner is null)
      due_date              datetime.date or None (only for a stated calendar date)
      due_phrase            str or None (deadline wording copied from the document)
      priority              exactly "high", "medium", or "low"
      evidence              str, at least 10 characters, a verbatim quote
    Also:
      - forbid extra fields (model_config = ConfigDict(extra="forbid"))
      - add a @model_validator(mode="after") that raises ValueError when owner is
        None and owner_missing_reason is empty. This rule can't be expressed in
        the API schema; the SDK still enforces it when it validates the reply.
    """

    pass


class Extraction(BaseModel):
    """Everything extracted from one document.

    TODO: forbid extra fields; one required field `items`: list[ActionItem], with a description.
    """

    pass


# ---------------------------------------------------------------- verification


@dataclass
class Flag:
    index: int
    task: str
    problems: list[str]


def normalize(text: str) -> str:
    """Collapse every run of whitespace into one space and strip the ends."""
    raise NotImplementedError("TODO")


def verify_evidence(extraction: Extraction, source: str) -> list[Flag]:
    """Flag items whose evidence or owner is not supported by the source text.

    Problems, in order:
      "evidence not found in source"  normalized evidence is empty or not a substring of the normalized source
      "owner not found in source"     owner is set but the name does not appear anywhere in the source
    """
    raise NotImplementedError("TODO")


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
    # TODO: the same formatting you wrote in lesson 7
    raise NotImplementedError("TODO")


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
    # TODO: implement. Use exactly this call shape:
    #     response = client.messages.parse(
    #         model=model,
    #         max_tokens=MAX_TOKENS,
    #         system=SYSTEM_PROMPT,
    #         messages=messages,
    #         output_format=Extraction,
    #     )
    # then response.stop_reason and response.parsed_output.
    raise NotImplementedError("TODO")


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
