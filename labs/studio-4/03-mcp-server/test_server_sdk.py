"""Tests for the MCP layer of lab 03 (Studio 4), through the SDK's in-memory Client.

Skipped unless the official SDK is installed:
    pip install "mcp[cli]"       # SDK 2.x, Python 3.11+
No API key, subprocess, or port is needed: Client(server) talks to the server object directly.
"""
from __future__ import annotations

import importlib.metadata
import json
import pathlib

import pytest

pytest.importorskip("mcp")
if int(importlib.metadata.version("mcp").split(".")[0]) < 2:
    pytest.skip("this lab targets the v2 SDK (MCPServer); pip install -U \"mcp[cli]\"", allow_module_level=True)
from mcp import Client  # noqa: E402

import starter as lab  # noqa: E402

DATA = pathlib.Path(__file__).parent / "data" / "issues.json"
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tracker_file(tmp_path) -> pathlib.Path:
    path = tmp_path / "issues.json"
    path.write_text(DATA.read_text(encoding="utf-8"), encoding="utf-8")
    return path


@pytest.fixture
async def client(tracker_file):
    async with Client(lab.build_server(tracker_file), raise_exceptions=True) as c:
        yield c


def text_of(result) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


async def test_exposes_the_four_tools_with_honest_annotations(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {"list_issues", "search_issues", "get_issue", "update_issue_status"}
    for name in ("list_issues", "search_issues", "get_issue"):
        assert tools[name].annotations and tools[name].annotations.read_only_hint is True, f"{name} only reads"
    write = tools["update_issue_status"]
    assert write.annotations and write.annotations.read_only_hint is False
    assert "confirm" in write.input_schema["properties"]
    for t in tools.values():
        assert t.description and len(t.description) > 60, f"{t.name} needs a real description"


async def test_read_tool_returns_data(client):
    result = await client.call_tool("list_issues", {"status": "blocked"})
    assert result.is_error is False
    assert "HAR-104" in text_of(result)


async def test_bad_input_is_a_tool_error_the_model_can_read(client):
    result = await client.call_tool("get_issue", {"issue_id": "ticket 7"})
    assert result.is_error is True
    assert "HAR-101" in text_of(result), "the error should show the expected format"


async def test_write_needs_confirmation_then_persists(client, tracker_file):
    preview = await client.call_tool("update_issue_status", {"issue_id": "HAR-102", "new_status": "in_progress"})
    assert preview.is_error is False and "requires_confirmation" in text_of(preview)
    assert json.loads(tracker_file.read_text())["issues"][1]["status"] == "open", "a preview must not write"

    done = await client.call_tool(
        "update_issue_status", {"issue_id": "HAR-102", "new_status": "in_progress", "confirm": True}
    )
    assert done.is_error is False
    assert json.loads(tracker_file.read_text())["issues"][1]["status"] == "in_progress"


async def test_summary_resource_and_issue_template(client):
    uris = [str(r.uri) for r in (await client.list_resources()).resources]
    assert "tracker://summary" in uris
    templates = [t.uri_template for t in (await client.list_resource_templates()).resource_templates]
    assert "tracker://issues/{issue_id}" in templates
    summary = await client.read_resource("tracker://summary")
    assert "Open launch blockers" in summary.contents[0].text
    issue = await client.read_resource("tracker://issues/HAR-101")
    assert json.loads(issue.contents[0].text)["id"] == "HAR-101"


async def test_triage_prompt(client):
    prompts = {p.name: p for p in (await client.list_prompts()).prompts}
    assert "triage_issue" in prompts
    assert [a.name for a in prompts["triage_issue"].arguments] == ["issue_id"]
    result = await client.get_prompt("triage_issue", {"issue_id": "HAR-104"})
    assert "HAR-104" in result.messages[0].content.text
