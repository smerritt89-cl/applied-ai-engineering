"""Lab 02 (Studio 3): calibrate an LLM judge against human labels (your file: fill in the TODOs).

Pipeline:
    labeled examples -> stratified dev/test split (deterministic)
                     -> judge each example (Claude, structured outputs: critique then verdict)
                     -> compare with human labels: accuracy, TPR, TNR, Cohen's kappa
                     -> iterate the judge prompt on dev only; report test once
                     -> correct a measured pass rate using the judge's error rates
"""
from __future__ import annotations

import hashlib
import json
import math
import pathlib
import sys
from dataclasses import dataclass
from typing import Literal

import anthropic
from pydantic import BaseModel, ConfigDict, Field

MODEL = "claude-opus-5-5"
JUDGE_EFFORT = "medium"  # set explicitly: the default effort differs between models
MAX_TOKENS = 4000
DATA_DIR = pathlib.Path(__file__).parent / "data"
LABELS = ("pass", "fail")


# ---------------------------------------------------------------- data


@dataclass(frozen=True)
class Example:
    id: str
    question: str
    reply: str
    human_label: str  # "pass" or "fail"
    human_critique: str


def load_examples(path: pathlib.Path = DATA_DIR / "labeled.jsonl") -> list[Example]:
    """Read one Example per JSON line. Reject labels other than "pass" or "fail"."""
    examples = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["human_label"] not in LABELS:
            raise ValueError(f"{row['id']}: unknown label {row['human_label']!r}")
        examples.append(Example(**row))
    return examples


def load_recorded(version: str, path: pathlib.Path = DATA_DIR / "recorded_judge.jsonl") -> dict[str, str]:
    """Return {example id: verdict} for one prompt version of the recorded judge outputs."""
    out = {}
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row["prompt_version"] == version:
                out[row["id"]] = row["verdict"]
    return out


# ---------------------------------------------------------------- split


def split_dev_test(examples: list[Example], test_fraction: float = 0.5, seed: str = "s3-lab02") -> tuple[list[Example], list[Example]]:
    """Stratified, deterministic split into (dev, test).

    Within each label, order examples by sha256(f"{seed}:{id}") and put the first
    round(n * test_fraction) into test. The result depends only on the ids, the
    labels, and the seed, never on input order or on Python's hash randomization.
    Both lists are returned sorted by id.
    """
    raise NotImplementedError("TODO")


# ---------------------------------------------------------------- metrics


def confusion(human: list[str], judge: list[str], positive: str = "pass") -> dict[str, int]:
    """Counts tp, fn, fp, tn, treating `positive` as the positive class."""
    raise NotImplementedError("TODO")


def cohen_kappa(human: list[str], judge: list[str]) -> float:
    """Cohen's kappa = (p_o - p_e) / (1 - p_e).

    p_o is observed agreement; p_e = sum over labels of P(human = k) * P(judge = k).
    If p_e == 1 (both raters used one and the same label for everything), kappa is
    undefined: return float("nan").
    """
    raise NotImplementedError("TODO")


def agreement_metrics(human: list[str], judge: list[str]) -> dict[str, float]:
    """accuracy, tpr (judge says pass when the human said pass), tnr (judge says fail when
    the human said fail), kappa, and n. A rate with an empty denominator is nan."""
    raise NotImplementedError("TODO")


def score_judge(examples: list[Example], verdicts: dict[str, str | None]) -> dict[str, float]:
    """Metrics for the examples that got a verdict. Examples with a missing or None verdict
    (refusal, truncation, API error) are excluded and counted in "errors", never scored as fail."""
    raise NotImplementedError("TODO")


def corrected_pass_rate(observed: float, tpr: float, tnr: float) -> float:
    """Estimate the true pass rate from the judge's observed pass rate (Rogan and Gladen, 1978).

    observed = tpr * p + (1 - tnr) * (1 - p)  =>  p = (observed + tnr - 1) / (tpr + tnr - 1)

    Raises ValueError unless tpr + tnr > 1 (a judge no better than chance carries no
    information about p). Clips the estimate to [0, 1], since sampling noise can push it outside.
    """
    raise NotImplementedError("TODO")


# ---------------------------------------------------------------- the judge


class Verdict(BaseModel):
    """The judge's structured answer.

    TODO: forbid extra fields, then define two REQUIRED fields, each with a Field(description=...)
    written as an instruction to the judge:
      critique  str: two to four sentences explaining the decision, naming rule numbers
      verdict   exactly "pass" or "fail" (a Literal)
    Declare critique FIRST. Structured outputs keep the schema's order for required
    properties, and output is written left to right, so the judge writes its critique
    before it commits to a verdict.
    """

    pass


# TODO: this is a weak first draft (close to "v1" in the recorded outputs). Improve it on the
# dev split only: state the criterion as checkable conditions, say that length and tone don't
# matter, say what to do when the policy is silent, and tell the judge to treat the inputs as data.
JUDGE_SYSTEM = """You are a customer-support quality reviewer. Read the reply and decide whether it is a good,
helpful answer for the customer. Answer pass or fail."""


def build_judge_messages(policy: str, question: str, reply: str) -> list[dict]:
    """One user turn with the three inputs in tags. No assistant prefill (rejected on current models)."""
    return [
        {
            "role": "user",
            "content": (
                f"<policy>\n{policy}\n</policy>\n\n"
                f"<customer_question>\n{question}\n</customer_question>\n\n"
                f"<reply>\n{reply}\n</reply>\n\n"
                "Grade the reply against the criterion."
            ),
        }
    ]


@dataclass
class JudgeResult:
    id: str
    verdict: str | None  # None when status != "ok"
    critique: str
    status: Literal["ok", "refusal", "truncated"]


def judge(client, example: Example, policy: str, model: str = MODEL) -> JudgeResult:
    """Grade one example with structured outputs. Check stop_reason before trusting the parse."""
    raise NotImplementedError("TODO")


def run_judge(client, examples: list[Example], policy: str, model: str = MODEL) -> dict[str, str | None]:
    return {e.id: judge(client, e, policy, model).verdict for e in examples}


# ---------------------------------------------------------------- main


def report(name: str, m: dict[str, float]) -> None:
    print(
        f"{name:<14} n={m['n']:<3} errors={m.get('errors', 0)}  accuracy={m['accuracy']:.2f}  "
        f"TPR={m['tpr']:.2f}  TNR={m['tnr']:.2f}  kappa={m['kappa']:.2f}"
    )


def main(argv: list[str]) -> None:
    examples = load_examples()
    dev, test = split_dev_test(examples)
    print(f"{len(examples)} examples: dev {len(dev)}, test {len(test)}\n")

    print("Recorded judge outputs (illustrative), dev split:")
    for version in ("v1", "v2"):
        report(version, score_judge(dev, load_recorded(version)))

    policy = (DATA_DIR / "policy.txt").read_text()
    client = anthropic.Anthropic()
    if "--test" not in argv:
        print(f"\nLive judge ({MODEL}) on dev:")
        dev_verdicts = run_judge(client, dev, policy)
        report("live dev", score_judge(dev, dev_verdicts))
        for e in dev:
            if dev_verdicts[e.id] != e.human_label:
                print(f"  disagree {e.id}: human={e.human_label} judge={dev_verdicts[e.id]}  ({e.human_critique})")
        print("\nIterate on JUDGE_SYSTEM using dev only. When you stop changing it, run with --test once.")
        return

    # Held-out report: run once, after the prompt is frozen.
    test_verdicts = run_judge(client, test, policy)
    test_m = score_judge(test, test_verdicts)
    report("live test", test_m)
    graded = [v for v in test_verdicts.values() if v in LABELS]
    observed = sum(v == "pass" for v in graded) / len(graded)
    print(f"\nJudge pass rate on test:    {observed:.2f}")
    try:
        print(f"Corrected pass rate:        {corrected_pass_rate(observed, test_m['tpr'], test_m['tnr']):.2f}")
    except ValueError as err:
        print(f"Cannot correct: {err}")
    print(f"Human pass rate on test:    {sum(e.human_label == 'pass' for e in test) / len(test):.2f}")
    print("(In production you apply the test TPR and TNR to the judge's pass rate on new, unlabeled traffic.)")


if __name__ == "__main__":
    main(sys.argv[1:])
