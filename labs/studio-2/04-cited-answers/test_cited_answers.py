"""Tests for Studio 2 lab 04. Offline tests need no API key; @pytest.mark.live tests call Claude.

Run:  pytest studio-2/04-cited-answers -q
"""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import pytest

import starter as lab

HERE = pathlib.Path(__file__).parent
FIXTURES = HERE / "fixtures"


def fixture(name: str):
    path = FIXTURES / name
    return json.loads(path.read_text()) if path.suffix == ".json" else path.read_text()


@pytest.fixture
def passages():
    return lab.load_passages()


# ---------------------------------------------------------------- 1. the request


def test_one_search_result_per_passage_with_ids_as_sources(passages):
    blocks = lab.build_search_results(passages)
    assert blocks is not None, "build_search_results returned None"
    assert len(blocks) == len(passages)
    first = blocks[0]
    assert first["type"] == "search_result"
    assert first["source"] == passages[0].id, "put the passage id in `source` so citations name it"
    assert first["title"] == passages[0].title
    assert first["content"] == [{"type": "text", "text": passages[0].text}]


def test_citations_enabled_on_every_search_result(passages):
    blocks = lab.build_search_results(passages)
    assert all(b.get("citations") == {"enabled": True} for b in blocks), (
        "enable citations on every search result: the API requires the same setting on all of them"
    )


def test_sources_first_question_last_single_user_turn(passages):
    msgs = lab.build_messages("Can I expense an upgrade?", passages)
    assert len(msgs) == 1 and msgs[0]["role"] == "user", "one user turn; no assistant prefill"
    content = msgs[0]["content"]
    assert [b["type"] for b in content[:-1]] == ["search_result"] * len(passages), "all sources first"
    assert content[-1] == {"type": "text", "text": "Can I expense an upgrade?"}, "the question goes last"


def test_system_prompt_restricts_to_sources_and_defines_abstention():
    prompt = lab.SYSTEM_PROMPT.lower()
    assert "only" in prompt, "tell the model to answer only from the provided sources"
    assert lab.ABSTAIN_PHRASE in lab.SYSTEM_PROMPT, "give the model the exact abstention sentence"


# ---------------------------------------------------------------- 2. parsing


def test_parse_ok_fixture_skips_thinking_and_keeps_every_text_block():
    answer = lab.parse_claude_response(fixture("claude_ok.json"))
    assert answer is not None, "parse_claude_response returned None"
    assert len(answer.claims) == 4, "four text blocks; the thinking block is skipped"
    assert answer.stop_reason == "end_turn"
    assert [len(c.citations) for c in answer.claims] == [0, 1, 0, 1]
    cit = answer.claims[1].citations[0]
    assert cit.passage_id == "travel-002"
    assert cit.search_result_index == 1
    assert cit.quote.startswith("Hotel stays are reimbursed"), "the quote is the API's cited_text"
    assert answer.text.startswith("Usually not. Room upgrades")


def test_parse_reads_sdk_style_objects_too():
    citation = SimpleNamespace(
        type="search_result_location", source="expense-010", cited_text="Alcohol is not reimbursable.",
        search_result_index=2, title="Meals", start_block_index=0, end_block_index=1,
    )
    other = SimpleNamespace(type="char_location", cited_text="ignored", document_index=0)
    response = SimpleNamespace(
        stop_reason="end_turn",
        content=[
            SimpleNamespace(type="thinking", thinking="", signature="x"),
            SimpleNamespace(type="text", text="No.", citations=[citation, other]),
        ],
    )
    answer = lab.parse_claude_response(response)
    assert len(answer.claims) == 1
    assert [c.passage_id for c in answer.claims[0].citations] == ["expense-010"], (
        "keep only search_result_location citations"
    )


def test_parse_marked_answer_from_another_provider():
    answer = lab.parse_marked_answer(fixture("marked_answer.txt"))
    assert answer is not None, "parse_marked_answer returned None"
    assert len(answer.claims) == 4, "one claim per non-empty line"
    first = answer.claims[0]
    assert first.text == "Business class is allowed on flights over 4 hours without approval.", (
        "strip the markers and collapse whitespace"
    )
    assert [(c.passage_id, c.quote) for c in first.citations] == [
        ("faq-020", "any flight over 4 hours may be booked in business class without approval")
    ]
    assert first.citations[0].search_result_index is None
    assert answer.claims[3].citations == []


# ---------------------------------------------------------------- 3. verification


def test_normalize_collapses_whitespace():
    assert lab.normalize("  a \n b\t\tc  ") == "a b c"


def test_ok_fixture_verifies_clean(passages):
    report = lab.verify_answer(lab.parse_claude_response(fixture("claude_ok.json")), passages)
    assert report is not None, "verify_answer returned None"
    assert report.ok and report.problems == []
    assert report.uncited == [], "short connective text is not a claim that needs a citation"
    assert report.cited_claims == 2
    assert report.abstained is False


def test_tampered_fixture_catches_each_kind_of_bad_citation(passages):
    report = lab.verify_answer(lab.parse_claude_response(fixture("claude_tampered.json")), passages)
    kinds = [(p.claim_index, p.kind) for p in report.problems]
    assert kinds == [
        (1, "index mismatch"),
        (2, "quote not in passage"),
        (3, "unknown passage"),
    ], f"got {kinds}"
    assert report.uncited == [4], "an uncited sentence with a number in it needs a look"
    assert report.cited_claims == 1
    assert not report.ok


def test_marked_answer_flags_the_paraphrase_but_not_the_outdated_source(passages):
    report = lab.verify_answer(lab.parse_marked_answer(fixture("marked_answer.txt")), passages)
    assert [(p.claim_index, p.kind) for p in report.problems] == [(2, "quote not in passage")], (
        "'Economy class is default' drops a word from the passage"
    )
    assert report.uncited == [3]
    # Claim 0 quotes the archived 2023 FAQ verbatim. It passes every mechanical check,
    # and it is still the wrong answer. See the README.
    assert 0 not in [p.claim_index for p in report.problems]


def test_empty_quote_is_never_verified(passages):
    answer = lab.CitedAnswer(claims=[lab.Claim("Alcohol is not covered.", [lab.Citation("expense-010", "  ")])])
    report = lab.verify_answer(answer, passages)
    assert [p.kind for p in report.problems] == ["quote not in passage"], '"" is a substring of every string'


def test_quote_matching_survives_line_breaks(passages):
    quote = "Alcohol is not\n   reimbursable."
    answer = lab.CitedAnswer(claims=[lab.Claim("No alcohol.", [lab.Citation("expense-010", quote)])])
    assert lab.verify_answer(answer, passages).ok


def test_abstention_is_recognized(passages):
    report = lab.verify_answer(lab.parse_claude_response(fixture("claude_abstain.json")), passages)
    assert report.abstained is True
    assert report.ok and report.uncited == []


def test_abstain_phrase_with_citations_is_not_an_abstention(passages):
    answer = lab.CitedAnswer(
        claims=[
            lab.Claim(lab.ABSTAIN_PHRASE + " "),
            lab.Claim("Alcohol is not reimbursable.", [lab.Citation("expense-010", "Alcohol is not reimbursable.")]),
        ]
    )
    assert lab.verify_answer(answer, passages).abstained is False


# ---------------------------------------------------------------- 4. the call, with a fake client


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response

    def parse(self, **kwargs):
        raise AssertionError("citations are incompatible with structured outputs; use create()")


class FakeClient:
    def __init__(self, response):
        self.messages = FakeMessages(response)


def as_response(name: str):
    """Wrap a fixture so it behaves like an SDK object at the top level."""
    data = fixture(name)
    return SimpleNamespace(**data)


def test_call_shape(passages):
    client = FakeClient(as_response("claude_ok.json"))
    answer = lab.answer_with_citations(client, "Can I expense a hotel room upgrade?", passages)
    assert len(client.messages.calls) == 1
    call = client.messages.calls[0]
    assert call["model"] == lab.MODEL
    assert call["max_tokens"] >= 1024
    assert call["system"] == lab.SYSTEM_PROMPT
    assert call["messages"] == lab.build_messages("Can I expense a hotel room upgrade?", passages)
    for banned in ("temperature", "top_p", "top_k", "output_format"):
        assert banned not in call, f"{banned} must not be sent"
    assert "format" not in (call.get("output_config") or {}), "structured outputs return a 400 with citations"
    assert answer.claims and answer.claims[1].citations[0].passage_id == "travel-002"


@pytest.mark.parametrize("reason", ["refusal", "max_tokens"])
def test_bad_stop_reasons_raise(passages, reason):
    response = as_response("claude_ok.json")
    response.stop_reason = reason
    with pytest.raises(lab.AnswerFailed):
        lab.answer_with_citations(FakeClient(response), "Q?", passages)


# ---------------------------------------------------------------- 5. live


@pytest.mark.live
def test_live_answerable_question_is_cited_and_verifies(passages):
    import anthropic

    answer = lab.answer_with_citations(anthropic.Anthropic(), "Can I expense a hotel room upgrade?", passages)
    report = lab.verify_answer(answer, passages)
    print("\n" + answer.text)
    print("problems:", report.problems, "uncited:", report.uncited)
    assert report.cited_claims >= 1, "the answer should cite at least one passage"
    assert report.ok, "API citations should always point at real passages with verbatim text"
    cited = {c.passage_id for claim in answer.claims for c in claim.citations}
    assert "travel-002" in cited, "the hotel passage is the one that answers this"


@pytest.mark.live
def test_live_unanswerable_question_abstains_or_stays_uncited(passages):
    import anthropic

    answer = lab.answer_with_citations(
        anthropic.Anthropic(), "What is the per diem for international travel in Japan?", passages
    )
    report = lab.verify_answer(answer, passages)
    print("\n" + answer.text)
    # The corpus has a domestic meal limit, not a Japan per diem. A good answer abstains, or
    # cites the meal limit while saying it does not cover the question. Read the output.
    assert report.ok
