"""Lab 04 (Studio 3): evaluate a RAG system (reference solution).

Pipeline:
    fixture RAG outputs -> retrieval metrics (recall@k, precision@k, MRR) against labeled relevant chunks
                        -> split each answer into claims
                        -> judge each claim against the retrieved context (Claude live, or recorded judgments offline)
                        -> faithfulness per answer, with a bootstrap confidence interval
                        -> judge agreement with human labels (TPR, TNR)
                        -> a one-page Markdown report a stakeholder can read

Run offline (recorded judgments):   python solution.py
Run with a live judge:              python solution.py --live
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import re
import statistics
from dataclasses import dataclass

import anthropic
from pydantic import BaseModel, ConfigDict, Field

HERE = pathlib.Path(__file__).parent
FIXTURES = HERE / "fixtures"
JUDGE_MODEL = "claude-opus-5-5"
MAX_TOKENS = 4000

JUDGE_SYSTEM = """You check whether a single claim is supported by retrieved passages from a company handbook.

A claim is SUPPORTED only if the passages state it, or it follows directly from what they state, with no outside
knowledge and no assumptions. A claim that adds a number, a condition, a promise, or a permission the passages do not
contain is NOT supported, even if it sounds plausible. If the passages are silent, the claim is not supported.

Write a one-sentence reason first, then the verdict."""


# ---------------------------------------------------------------- 1. retrieval metrics


def recall_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    """Fraction of the relevant chunk ids that appear in the top k retrieved ids.
    Raise ValueError if relevant is empty (recall is undefined)."""
    if not relevant:
        raise ValueError("recall is undefined when there are no relevant items")
    top = set(retrieved[:k])
    return sum(1 for r in set(relevant) if r in top) / len(set(relevant))


def precision_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    """Fraction of the top k slots filled by relevant ids. Always divide by k."""
    rel = set(relevant)
    return sum(1 for doc in retrieved[:k] if doc in rel) / k


def reciprocal_rank(retrieved: list[str], relevant: list[str]) -> float:
    """1 / (1-based rank of the first relevant id), or 0.0 if none was retrieved."""
    rel = set(relevant)
    for rank, doc in enumerate(retrieved, start=1):
        if doc in rel:
            return 1 / rank
    return 0.0


def retrieval_metrics(cases: list[dict], ks: tuple[int, ...] = (3, 5)) -> dict[str, float]:
    """Mean recall@k and precision@k for each k, plus MRR, over all cases."""
    out: dict[str, float] = {}
    for k in ks:
        out[f"recall@{k}"] = statistics.fmean(recall_at_k(c["retrieved"], c["relevant"], k) for c in cases)
        out[f"precision@{k}"] = statistics.fmean(precision_at_k(c["retrieved"], c["relevant"], k) for c in cases)
    out["mrr"] = statistics.fmean(reciprocal_rank(c["retrieved"], c["relevant"]) for c in cases)
    return out


# ---------------------------------------------------------------- 2. claims and faithfulness

CITATION = re.compile(r"\s*\[[^\]]+\]")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def split_claims(answer: str) -> list[str]:
    """Split an answer into checkable claims.
    1. Remove citation markers such as [pto-2] (and the whitespace before them).
    2. Split into sentences at . ! or ? followed by whitespace.
    3. Strip each sentence; drop empty ones and any with fewer than 3 words (like "Yes.")."""
    text = CITATION.sub("", answer)
    parts = [p.strip() for p in SENTENCE_END.split(text)]
    return [p for p in parts if p and len(p.split()) >= 3]


def faithfulness(case: dict, chunks: dict[str, str], judge) -> float | None:
    """Fraction of the answer's claims the judge says are supported by the retrieved chunks.
    Return None for abstentions or answers with no claims (they are reported separately, not scored as 1.0).
    judge(case_id, claim, contexts) -> bool, where contexts is the list of retrieved chunk texts in rank order."""
    if case.get("abstained"):
        return None
    claims = split_claims(case["answer"])
    if not claims:
        return None
    contexts = [chunks[c] for c in case["retrieved"]]
    supported = sum(1 for claim in claims if judge(case["id"], claim, contexts))
    return supported / len(claims)


# ---------------------------------------------------------------- 3. checking the judge


def judge_agreement(judge_labels: list[bool], human_labels: list[bool]) -> dict[str, float]:
    """Agreement of the judge with human labels, treating "supported" (True) as the positive class.
      tpr: of the claims humans marked supported, the fraction the judge also marked supported
      tnr: of the claims humans marked unsupported, the fraction the judge also marked unsupported
      n:   number of labeled claims
    Raise ValueError if the lists differ in length or either class is missing from the human labels."""
    if len(judge_labels) != len(human_labels):
        raise ValueError("judge and human label lists must be the same length")
    pos = [j for j, h in zip(judge_labels, human_labels) if h]
    neg = [j for j, h in zip(judge_labels, human_labels) if not h]
    if not pos or not neg:
        raise ValueError("need human labels of both classes to estimate TPR and TNR")
    return {"tpr": sum(pos) / len(pos), "tnr": sum(1 for j in neg if not j) / len(neg), "n": len(human_labels)}


# ---------------------------------------------------------------- 4. uncertainty


def bootstrap_ci(values: list[float], n_resamples: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap confidence interval for the mean.
    Resample len(values) items with replacement n_resamples times (use random.Random(seed)),
    take each resample's mean, and return the alpha/2 and 1 - alpha/2 quantiles of those means.
    Raise ValueError for an empty list."""
    if not values:
        raise ValueError("need at least one value")
    rng = random.Random(seed)
    n = len(values)
    means = sorted(statistics.fmean(rng.choices(values, k=n)) for _ in range(n_resamples))
    lo = means[int((alpha / 2) * (n_resamples - 1))]
    hi = means[int((1 - alpha / 2) * (n_resamples - 1))]
    return lo, hi


# ---------------------------------------------------------------- 5. judges


class Verdict(BaseModel):
    """The judge's decision about one claim."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(description="One sentence citing what the passages do or do not say about the claim")
    supported: bool = Field(description="true only if the passages state or directly imply the claim")


class JudgeFailed(Exception):
    """Raised when the judge produced no usable verdict."""


def build_judge_messages(claim: str, contexts: list[str]) -> list[dict]:
    """One user turn: each passage in its own <passage index="i"> tag, then the claim in <claim> tags."""
    passages = "\n".join(f'<passage index="{i}">\n{text}\n</passage>' for i, text in enumerate(contexts, start=1))
    return [
        {
            "role": "user",
            "content": f"<passages>\n{passages}\n</passages>\n\n<claim>{claim}</claim>\n\nIs the claim supported by the passages?",
        }
    ]


def judge_claim(client, claim: str, contexts: list[str], model: str = JUDGE_MODEL) -> Verdict:
    """Ask Claude whether the claim is supported, using structured outputs (messages.parse with output_format=Verdict).
    Raise JudgeFailed if stop_reason is "refusal" or "max_tokens", or parsed_output is None."""
    response = client.messages.parse(
        model=model,
        max_tokens=MAX_TOKENS,
        system=JUDGE_SYSTEM,
        messages=build_judge_messages(claim, contexts),
        output_format=Verdict,
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        raise JudgeFailed(f"judge stopped with {response.stop_reason}")
    if response.parsed_output is None:
        raise JudgeFailed("judge returned no parsed verdict")
    return response.parsed_output


@dataclass
class LiveJudge:
    """Callable judge backed by Claude. Records every verdict so you can save and replay them."""

    client: object
    model: str = JUDGE_MODEL

    def __post_init__(self):
        self.records: list[dict] = []

    def __call__(self, case_id: str, claim: str, contexts: list[str]) -> bool:
        verdict = judge_claim(self.client, claim, contexts, self.model)
        self.records.append({"case_id": case_id, "claim": claim, "supported": verdict.supported, "reason": verdict.reason})
        return verdict.supported


class RecordedJudge:
    """Replays saved judgments, keyed by (case_id, claim text). Used by the offline tests."""

    def __init__(self, path: pathlib.Path = FIXTURES / "recorded_judgments.json"):
        data = json.loads(pathlib.Path(path).read_text())
        self.model = data.get("model", "recorded")
        self.lookup = {(r["case_id"], r["claim"]): r["supported"] for r in data["judgments"]}

    def __call__(self, case_id: str, claim: str, contexts: list[str]) -> bool:
        try:
            return self.lookup[(case_id, claim)]
        except KeyError:
            raise KeyError(
                f"no recorded judgment for {case_id!r}: {claim!r}. "
                "Check split_claims: claims must match the recorded text exactly."
            ) from None


# ---------------------------------------------------------------- 6. evaluate and report


def load_fixture(path: pathlib.Path = FIXTURES / "rag_outputs.json") -> dict:
    return json.loads(pathlib.Path(path).read_text())


def load_human_labels(path: pathlib.Path = FIXTURES / "human_labels.json") -> dict[tuple[str, str], bool]:
    data = json.loads(pathlib.Path(path).read_text())
    return {(r["case_id"], r["claim"]): r["supported"] for r in data["labels"]}


def evaluate(fixture: dict, judge, human_labels: dict | None = None, ks: tuple[int, ...] = (3, 5), judge_name: str = "recorded") -> dict:
    """Glue code (provided): runs every metric and returns the summary dict that build_report formats."""
    cases, chunks = fixture["cases"], fixture["chunks"]
    memo: dict[tuple[str, str], bool] = {}

    def cached(case_id: str, claim: str, contexts: list[str]) -> bool:
        # Judge each claim once, so live runs pay once and both metrics see the same verdict.
        if (case_id, claim) not in memo:
            memo[(case_id, claim)] = bool(judge(case_id, claim, contexts))
        return memo[(case_id, claim)]

    per_case = {c["id"]: faithfulness(c, chunks, cached) for c in cases}
    scored = [v for v in per_case.values() if v is not None]
    max_k = max(ks)
    misses = [c["id"] for c in cases if recall_at_k(c["retrieved"], c["relevant"], max_k) < 1.0]
    summary = {
        "n_cases": len(cases),
        "ks": list(ks),
        "retrieval": retrieval_metrics(cases, ks),
        "retrieval_misses": misses,
        "faithfulness": {
            "mean": statistics.fmean(scored) if scored else None,
            "ci": bootstrap_ci(scored) if scored else None,
            "n_scored": len(scored),
            "n_abstained": sum(1 for c in cases if c.get("abstained")),
            "per_case": per_case,
        },
        "judge": judge_name,
        "judge_agreement": None,
    }
    if human_labels:
        judged, human = [], []
        for c in cases:
            if c.get("abstained"):
                continue
            contexts = [chunks[x] for x in c["retrieved"]]
            for claim in split_claims(c["answer"]):
                if (c["id"], claim) in human_labels:
                    judged.append(cached(c["id"], claim, contexts))
                    human.append(human_labels[(c["id"], claim)])
        if judged:
            summary["judge_agreement"] = judge_agreement(judged, human)
    return summary


def build_report(summary: dict) -> str:
    """Format the summary as a one-page Markdown report for a mixed audience.

    Required, in this order:
      "# RAG evaluation report"
      "## Bottom line"     2 to 4 plain-language sentences a non-engineer can act on. Mention the number of
                           questions, the faithfulness mean with its 95% interval, and the main retrieval weakness.
      "## Retrieval"       a Markdown table with one row per metric in summary["retrieval"] (name | value),
                           and a line listing the ids of questions whose relevant chunks were not all retrieved.
      "## Faithfulness"    the mean and interval, how many answers were scored, how many abstained, the judge
                           name, and the ids of answers that scored below 1.0.
      "## Judge check"     TPR, TNR, and n if summary["judge_agreement"] is set; otherwise say the judge has not
                           been checked against human labels.
      "## Caveats"         at least the sample size and that the faithfulness numbers come from an LLM judge.
    Format every rate with two decimals (0.81, not 0.8125)."""
    r = summary["retrieval"]
    f = summary["faithfulness"]
    ks = summary["ks"]
    n = summary["n_cases"]
    misses = summary["retrieval_misses"]
    max_k = max(ks)
    agree = summary["judge_agreement"]

    if f["mean"] is not None:
        lo, hi = f["ci"]
        faith_line = f"{f['mean']:.2f} (95% CI {lo:.2f} to {hi:.2f})"
    else:
        faith_line = "not available (no scored answers)"
    low = [cid for cid, v in f["per_case"].items() if v is not None and v < 1.0]

    lines = ["# RAG evaluation report", ""]
    lines += [
        "## Bottom line",
        "",
        f"On {n} test questions, answers were faithful to the retrieved documents at a rate of {faith_line}.",
        f"Retrieval is the main weakness: for {len(misses)} of {n} questions the right passages were not all in the "
        f"top {max_k} results ({', '.join(misses) or 'none'}), and an answer can only be as good as what it retrieves.",
        "Treat these as directional: the sample is small and faithfulness is scored by an LLM judge.",
        "",
        "## Retrieval",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    lines += [f"| {name} | {value:.2f} |" for name, value in r.items()]
    lines += ["", f"Questions missing relevant passages in the top {max_k}: {', '.join(misses) or 'none'}.", ""]
    lines += [
        "## Faithfulness",
        "",
        f"Mean faithfulness: {faith_line}.",
        f"Scored answers: {f['n_scored']}. Abstained: {f['n_abstained']} (reported separately, not counted as faithful).",
        f"Judge: {summary['judge']}.",
        f"Answers with at least one unsupported claim: {', '.join(low) or 'none'}.",
        "",
        "## Judge check",
        "",
    ]
    if agree:
        lines.append(
            f"Against human labels on {agree['n']} claims: TPR {agree['tpr']:.2f} (supported claims the judge accepted), "
            f"TNR {agree['tnr']:.2f} (unsupported claims the judge caught)."
        )
        if agree["tnr"] < 0.8:
            lines.append("The judge misses unsupported claims often enough that faithfulness above is likely overstated.")
    else:
        lines.append("The judge has not been checked against human labels, so treat faithfulness as unverified.")
    lines += [
        "",
        "## Caveats",
        "",
        f"- Sample size: n = {n} questions. Intervals this wide cannot separate small differences between systems.",
        "- Faithfulness comes from an LLM judge, which can be lenient or drift when the model or prompt changes.",
        "- Faithfulness is not correctness: an answer can match the retrieved text and still answer the question wrongly.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="judge claims with Claude instead of recorded judgments")
    parser.add_argument("--out", default=str(HERE / "report.md"))
    args = parser.parse_args()

    fixture = load_fixture()
    human = load_human_labels()
    if args.live:
        judge = LiveJudge(anthropic.Anthropic())
        name = f"{judge.model} (live)"
    else:
        judge = RecordedJudge()
        name = f"{judge.model} (recorded judgments)"
    summary = evaluate(fixture, judge, human_labels=human, judge_name=name)
    report = build_report(summary)
    pathlib.Path(args.out).write_text(report)
    print(report)
    if args.live:
        path = HERE / "live_judgments.json"
        path.write_text(json.dumps({"model": judge.model, "judgments": judge.records}, indent=2))
        print(f"Saved {len(judge.records)} live judgments to {path.name}. Compare them with recorded_judgments.json.")


if __name__ == "__main__":
    main()
