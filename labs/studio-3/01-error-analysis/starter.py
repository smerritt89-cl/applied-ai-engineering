"""Lab 01 (Studio 3): error analysis toolkit (your file: fill in the TODOs).

Pipeline:
    traces.jsonl  -> load_traces
    (you annotate) -> annotations.csv (outcome, open-code note, axial failure modes)
    taxonomy.json -> load_taxonomy
    load_annotations (validated against traces and taxonomy)
    count_failure_modes -> prioritize -> render_report (Markdown)

Optional live step: make_tuples + generate_queries turn defined dimensions into
synthetic test inputs with Claude (structured outputs via messages.parse).
"""
from __future__ import annotations

import csv
import itertools
import json
import pathlib
from collections import Counter
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field

DATA_DIR = pathlib.Path(__file__).parent / "data"
MODEL = "claude-opus-5-5"
MAX_TOKENS = 2000

TRACE_FIELDS = ("trace_id", "timestamp", "channel", "plan", "user_message", "retrieved", "bot_response")
OUTCOMES = ("pass", "fail")


# ---------------------------------------------------------------- data types


@dataclass(frozen=True)
class Trace:
    trace_id: str
    timestamp: str
    channel: str
    plan: str
    user_message: str
    retrieved: tuple[str, ...]
    bot_response: str


@dataclass(frozen=True)
class Annotation:
    trace_id: str
    outcome: str  # "pass" or "fail"
    note: str  # open code: free-text observation
    failure_modes: tuple[str, ...]  # axial codes from the taxonomy


@dataclass(frozen=True)
class Priority:
    mode: str
    count: int  # failing traces showing this mode
    rate: float  # count / annotated traces
    severity: int  # 1 (cosmetic) to 3 (harmful)
    score: float  # rate * severity


class AnnotationError(ValueError):
    """Raised when the annotation file has problems. The message lists every problem found."""


# ---------------------------------------------------------------- loading


def load_traces(path: str | pathlib.Path) -> list[Trace]:
    """Read one JSON object per line. Skip blank lines.

    Raise ValueError if a line is missing a field from TRACE_FIELDS or repeats a trace_id.
    """
    raise NotImplementedError("TODO")


def load_taxonomy(path: str | pathlib.Path) -> dict[str, dict]:
    """Read the failure taxonomy: {mode: {"definition": str, "severity": 1..3}}.

    Raise ValueError if a mode has an empty definition or a severity that is not an int from 1 to 3.
    """
    raise NotImplementedError("TODO")


def write_annotation_template(traces: list[Trace], path: str | pathlib.Path) -> None:
    """Write a CSV to annotate in a spreadsheet.

    Columns, in order: trace_id, user_message, bot_response, outcome, note, failure_modes.
    One row per trace, in trace order, with outcome, note, and failure_modes left blank.
    """
    raise NotImplementedError("TODO")


def parse_modes(cell: str) -> tuple[str, ...]:
    """Split a failure_modes cell on ';', strip whitespace, drop empties, de-duplicate keeping order."""
    raise NotImplementedError("TODO")


def load_annotations(
    path: str | pathlib.Path, traces: list[Trace], taxonomy: dict[str, dict] | None = None
) -> list[Annotation]:
    """Read and validate the annotation CSV. Extra columns are ignored.

    Rows with a blank outcome are not yet annotated: skip them. For every other row, collect problems:
      "unknown trace_id"                     trace_id is not in traces
      "duplicate trace_id"                   trace_id already annotated on an earlier row
      "outcome must be pass or fail"         outcome (case-insensitive, stripped) is something else
      "pass with failure modes"              outcome is pass but failure_modes is not empty
      "fail needs a note or a failure mode"  outcome is fail and both are empty
      "unknown failure mode: <mode>"         taxonomy is given and a mode is not in it (one problem per mode)
    If any problems were found, raise AnnotationError with one line per problem:
      "row <n> (<trace_id>): <problem>"   where n is the 1-based data row number (header excluded).
    Otherwise return the Annotations in file order.
    """
    raise NotImplementedError("TODO")


# ---------------------------------------------------------------- analysis


def count_failure_modes(annotations: list[Annotation]) -> Counter:
    """Number of FAILING traces that show each mode (a trace counts at most once per mode)."""
    raise NotImplementedError("TODO")


def uncoded_failures(annotations: list[Annotation]) -> list[str]:
    """trace_ids of failing traces that have a note but no failure mode yet (they still need axial coding)."""
    raise NotImplementedError("TODO")


def summarize(annotations: list[Annotation]) -> dict:
    """{"annotated": n, "passed": p, "failed": f, "pass_rate": p / n (0.0 when n is 0)}."""
    raise NotImplementedError("TODO")


def prioritize(counts: Counter, taxonomy: dict[str, dict], n_annotated: int) -> list[Priority]:
    """One Priority per mode with a nonzero count.

    rate = count / n_annotated; score = rate * severity.
    Sort by score (high first), then count (high first), then mode name (A to Z).
    Round the score to 9 decimal places in the sort key: 4/36 * 1 and 2/36 * 2 are equal on paper but
    can differ in the last bit as floats, and a tie must fall through to the count.
    """
    raise NotImplementedError("TODO")


def render_report(
    traces: list[Trace], annotations: list[Annotation], taxonomy: dict[str, dict], top_k: int = 3
) -> str:
    """Markdown report. Must contain, in order:

    1. "# Error analysis report"
    2. A summary line: "Annotated {a} of {t} traces: {p} pass, {f} fail (pass rate {r:.1%})."
    3. A table with header "| Rank | Failure mode | Traces | Rate | Severity | Score |" and one row per
       Priority, e.g. "| 1 | invented_feature | 9 | 25.0% | 3 | 0.75 |"
    4. "## Top issues", then for each of the first top_k priorities a "### {rank}. {mode}" heading,
       the taxonomy definition, and "Examples: " followed by up to 3 trace_ids (file order), comma-separated.
    5. If there are uncoded failures: "## Needs axial coding" and their trace_ids.
    6. "## Caveats" with a sentence that starts "Rates come from {a} annotated traces".
    """
    raise NotImplementedError("TODO")


# ---------------------------------------------------------------- optional live step: synthetic inputs

DIMENSIONS: dict[str, list[str]] = {
    "topic": ["refund", "integration", "feature how-to", "account security"],
    "plan": ["Starter", "Pro"],
    "style": ["terse", "frustrated", "multi-part question"],
}

GEN_SYSTEM = """You write realistic test messages that customers might send to the support chat of Tallyhub,
an invoicing app for small businesses. Write exactly one customer message for the profile you are given.
Write it the way a real customer would type: no greeting to an AI, no meta commentary, no mention of the profile."""


class SyntheticQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(description="The customer's message, written in their own voice")


def make_tuples(
    dimensions: dict[str, list[str]], exclude: Callable[[dict[str, str]], bool] | None = None
) -> list[dict[str, str]]:
    """Cross product of the dimension values, as dicts, in itertools.product order over the
    dimensions in the order given. Drop any tuple for which exclude(tuple) is True."""
    raise NotImplementedError("TODO")


def tuple_to_prompt(t: dict[str, str]) -> str:
    """User-turn text for one tuple: one 'name: value' line per dimension inside <profile> tags."""
    body = "\n".join(f"{k}: {v}" for k, v in t.items())
    return f"<profile>\n{body}\n</profile>\n\nWrite the customer's message."


class GenerationFailed(Exception):
    pass


def generate_queries(client, tuples: list[dict[str, str]], model: str = MODEL) -> list[dict]:
    """Step two of two-step generation: one call per tuple, so each message is written for one profile.

    Uses client.messages.parse(model=..., max_tokens=MAX_TOKENS, system=GEN_SYSTEM,
    messages=[{"role": "user", "content": tuple_to_prompt(t)}], output_format=SyntheticQuery).
    Raise GenerationFailed if stop_reason is "refusal" or "max_tokens", or parsed_output is None.
    Return [{"dimensions": t, "query": text}, ...] in tuple order.
    """
    raise NotImplementedError("TODO")


# ---------------------------------------------------------------- script


def main() -> None:
    traces = load_traces(DATA_DIR / "traces.jsonl")
    taxonomy = load_taxonomy(DATA_DIR / "taxonomy.json")
    annotations = load_annotations(DATA_DIR / "annotations.csv", traces, taxonomy)
    report = render_report(traces, annotations, taxonomy)
    out = pathlib.Path(__file__).parent / "report.md"
    out.write_text(report)
    print(report)
    print(f"(written to {out})")


if __name__ == "__main__":
    main()
