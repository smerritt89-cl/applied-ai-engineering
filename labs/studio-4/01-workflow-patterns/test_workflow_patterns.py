"""Tests for Studio 4 lab 01. Offline tests use a fake client with scripted replies; @pytest.mark.live tests call Claude.

Run:  pytest studio-4/01-workflow-patterns -q
"""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import pytest

import starter as lab

NOTES = (pathlib.Path(__file__).parent / "samples" / "weekly-sync.md").read_text()
CONFIDENTIAL = ("Bluebird", "margin")


# ---------------------------------------------------------------- fake client


def reply(text: str, stop_reason: str = "end_turn", thinking: bool = False):
    blocks = [SimpleNamespace(type="thinking", thinking="")] if thinking else []
    blocks.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, usage=SimpleNamespace(input_tokens=100, output_tokens=50))


class FakeClient:
    """Records every messages.create call and returns scripted replies in order."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.replies:
            raise AssertionError(f"unexpected extra model call #{len(self.calls)} to {kwargs.get('model')}")
        nxt = self.replies.pop(0)
        return nxt if not isinstance(nxt, str) else reply(nxt)

    def models_called(self):
        return [c["model"] for c in self.calls]


def fact(kind, text, owner, quote):
    return {"kind": kind, "text": text, "owner": owner, "quote": quote}


GOOD_FACTS = [
    fact("update", "SSO integration done and passed QA", "Marcus Lee", "the SSO integration is done and passed QA on Friday."),
    fact("decision", "Launch moves from Nov 20 to Dec 4", None, "We agreed to move the launch from Nov 20 to Dec 4"),
    fact("action", "Revised checkout mockups", "Dana Whitfield", "Dana will deliver the revised checkout mockups by Wednesday."),
    fact("risk", "Payments vendor rate limits unconfirmed", None, "the payments vendor still hasn't confirmed their API rate limits."),
]


def facts_json(items):
    return json.dumps({"items": items})


def verdict(passed, problems=()):
    return json.dumps({"pass": passed, "problems": list(problems)})


# ---------------------------------------------------------------- 1. one model call


def test_text_of_skips_thinking_blocks():
    assert lab.text_of(reply("hello", thinking=True)) == "hello"


@pytest.mark.parametrize("reason", ["refusal", "max_tokens"])
def test_text_of_raises_on_unusable_stop_reasons(reason):
    with pytest.raises(lab.StepFailed):
        lab.text_of(reply("partial", stop_reason=reason))


def test_text_of_raises_when_no_text():
    empty = SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking="")], stop_reason="end_turn")
    with pytest.raises(lab.StepFailed):
        lab.text_of(empty)


def test_call_shape():
    client = FakeClient(["ok"])
    out = lab.call(client, model="claude-haiku-5-5", system="sys", prompt="hi", effort="low", schema=lab.VERDICT_SCHEMA)
    assert out == "ok"
    kw = client.calls[0]
    assert kw["model"] == "claude-haiku-5-5" and kw["system"] == "sys"
    assert kw["max_tokens"] == lab.MAX_TOKENS
    assert kw["output_config"] == {"effort": "low", "format": lab.VERDICT_SCHEMA}
    assert kw["messages"] == [{"role": "user", "content": "hi"}], "one user message, no assistant prefill"
    for banned in ("temperature", "top_p", "top_k", "output_format"):
        assert banned not in kw, f"do not send {banned}"


def test_call_without_schema_sends_only_effort():
    client = FakeClient(["ok"])
    lab.call(client, model=lab.MODEL, system="s", prompt="p")
    assert client.calls[0]["output_config"] == {"effort": "medium"}


# ---------------------------------------------------------------- 2. routing


@pytest.mark.parametrize(
    "raw, expected",
    [("client", "client"), (" Exec.\n", "exec"), ("TEAM", "team"), ("client or exec?", None), ("executive", None), ("", None)],
)
def test_parse_audience(raw, expected):
    assert lab.parse_audience(raw) == expected


def test_route_uses_the_cheap_model_at_low_effort():
    client = FakeClient(["client"])
    route = lab.route_audience(client, "Send the customer a note on the relaunch")
    assert route.audience == "client" and route.fell_back is False
    assert client.calls[0]["model"] == lab.ROUTER_MODEL
    assert client.calls[0]["output_config"]["effort"] == "low"


def test_route_falls_back_safely_on_a_hedge():
    client = FakeClient(["Probably client, but it could be exec."])
    route = lab.route_audience(client, "Status please")
    assert route.audience == lab.FALLBACK_AUDIENCE == "team", "a confused router must never default to an external audience"
    assert route.fell_back is True and "Probably" in route.raw


# ---------------------------------------------------------------- 3. chaining with a gate


def test_gate_keeps_supported_facts_with_whitespace_differences():
    wrapped = fact("action", "CSV fix", "Marcus Lee", "Marcus will finish the CSV export\n   fix by Nov 14.")
    result = lab.gate_facts(GOOD_FACTS + [wrapped], NOTES)
    assert len(result.kept) == 5 and result.rejected == []


def test_gate_rejects_unsupported_facts_with_reasons():
    items = [
        fact("action", "Update checklist", "Priya Raman", ""),
        fact("risk", "Vendor might be late", None, "the vendor is probably going to be late"),
        fact("action", "Client call", "Jordan Kim", "Sam will tell the client about the new launch date"),
    ]
    result = lab.gate_facts(items, NOTES)
    assert result.kept == []
    assert [reason for _, reason in result.rejected] == ["empty quote", "quote not in notes", "owner not in notes"]


def test_extract_sends_the_schema_and_parses_json():
    client = FakeClient([facts_json(GOOD_FACTS)])
    items = lab.extract_facts(client, NOTES)
    assert items == GOOD_FACTS
    assert client.calls[0]["output_config"]["format"] == lab.FACTS_SCHEMA


def test_pipeline_stops_at_the_gate_before_drafting():
    bad = [fact("decision", "Launch cancelled", None, "We cancelled the launch.")]
    client = FakeClient(["team", facts_json(bad)])
    with pytest.raises(lab.GateFailed):
        lab.status_update(client, NOTES, "Team update please")
    assert len(client.calls) == 2, "no draft call may happen after the gate fails"


# ---------------------------------------------------------------- 4. evaluator-optimizer


def test_code_checks_word_limit_and_owners():
    long_draft = "word " * 130
    problems = lab.code_checks(long_draft, GOOD_FACTS, "exec")
    assert any(p.startswith("too long: 130 words (limit 120)") for p in problems)
    assert "missing owner: Dana Whitfield" in problems
    assert lab.code_checks("", GOOD_FACTS, "team") == ["draft is empty"]
    ok = "Dana Whitfield will deliver the mockups by Wednesday. Launch moves to Dec 4."
    assert lab.code_checks(ok, GOOD_FACTS, "team") == []


def test_code_checks_confidential_terms_only_for_client():
    draft = "Project Bluebird is on track. Dana Whitfield owns the mockups. Margins are fine."
    client_problems = lab.code_checks(draft, GOOD_FACTS, "client", CONFIDENTIAL)
    assert "confidential term: Bluebird" in client_problems and "confidential term: margin" in client_problems
    assert lab.code_checks(draft, GOOD_FACTS, "team", CONFIDENTIAL) == [], "internal audiences may use the codename"


def test_refine_approves_after_feedback():
    first = "Launch moves to Dec 4."  # missing Dana's name: code check fails, no review call
    second = "Launch moves to Dec 4. Dana Whitfield delivers mockups Wednesday."
    client = FakeClient([first, second, verdict(True)])
    result = lab.refine(client, GOOD_FACTS, "team")
    assert result.approved is True and result.rounds == 2 and result.draft == second
    assert result.history[0] == ["missing owner: Dana Whitfield"] and result.history[1] == []
    assert client.models_called() == [lab.MODEL, lab.MODEL, lab.EVALUATOR_MODEL], "skip the model review when code checks fail"
    second_prompt = client.calls[1]["messages"][0]["content"]
    assert "missing owner: Dana Whitfield" in second_prompt, "feed the specific problems back into the next draft"


def test_refine_gives_up_and_flags_for_review():
    draft = "Launch moves to Dec 4. Dana Whitfield delivers mockups Wednesday."
    client = FakeClient([draft, verdict(False, ["buries the vendor risk"]), draft, verdict(False, [])])
    result = lab.refine(client, GOOD_FACTS, "team", max_rounds=2)
    assert result.approved is False and result.rounds == 2 and result.draft == draft
    assert result.history == [["buries the vendor risk"], ["reviewer rejected the draft without reasons"]]


def test_client_drafts_never_see_risks():
    draft = "The new launch date is Dec 4. Dana Whitfield is finishing the checkout designs."
    client = FakeClient([draft, verdict(True)])
    lab.refine(client, GOOD_FACTS, "client", CONFIDENTIAL)
    draft_prompt = client.calls[0]["messages"][0]["content"]
    assert "rate limits" not in draft_prompt, "risks must be filtered out before drafting a client update"


# ---------------------------------------------------------------- 5. end to end


def test_status_update_end_to_end():
    items = GOOD_FACTS + [fact("risk", "Margin is tight", None, "Margin on this project is tighter than planned")]
    leaky = "Bluebird launches Dec 4. Dana Whitfield owns the mockups."
    clean = "The portal now launches Dec 4. Dana Whitfield owns the checkout mockups."
    client = FakeClient(["client", facts_json(items), leaky, clean, verdict(True)])
    out = lab.status_update(client, NOTES, "Note for the customer, please", CONFIDENTIAL)
    assert out.route.audience == "client"
    assert len(out.gate.kept) == 5
    assert out.result.approved and out.result.draft == clean and out.result.rounds == 2
    assert client.models_called() == [lab.ROUTER_MODEL, lab.MODEL, lab.MODEL, lab.MODEL, lab.EVALUATOR_MODEL]


# ---------------------------------------------------------------- live


@pytest.mark.live
def test_live_pipeline_on_sample_notes():
    import anthropic

    out = lab.status_update(
        anthropic.Anthropic(),
        NOTES,
        "Can you send the client a quick note on where the portal relaunch stands?",
        confidential_terms=CONFIDENTIAL,
    )
    print(f"\nroute={out.route}\nrejected={[r for _, r in out.gate.rejected]}\nhistory={out.result.history}\n{out.result.draft}")
    assert out.route.audience == "client"
    assert out.gate.kept, "the sample notes contain several supported facts"
    assert lab.code_checks(out.result.draft, out.gate.kept, "client", CONFIDENTIAL) == [] or not out.result.approved
