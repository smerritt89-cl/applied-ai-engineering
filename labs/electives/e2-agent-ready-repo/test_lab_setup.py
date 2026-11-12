"""Offline checks for the lab's own infrastructure: the hooks configuration, the hook
scripts, the CLAUDE.md files, and the workspace builder. These pass out of the box;
if you edit the setups (you will, in the exercises), rerun them to catch mistakes.

Run:  pytest electives/e2-agent-ready-repo -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import make_workspace

LAB = Path(__file__).resolve().parent
FULL = LAB / "setups" / "full"
SETTINGS = FULL / ".claude" / "settings.json"

# Hook events listed in the Claude Code hooks guide (checked 2026-11-11). The list grows
# over time; a name outside it is far more likely a typo than a new event.
KNOWN_EVENTS = {
    "SessionStart", "Setup", "UserPromptSubmit", "UserPromptExpansion", "PreToolUse",
    "PermissionRequest", "PermissionDenied", "PostToolUse", "PostToolUseFailure", "PostToolBatch",
    "Notification", "MessageDisplay", "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted",
    "Stop", "StopFailure", "TeammateIdle", "InstructionsLoaded", "ConfigChange", "CwdChanged",
    "DirectoryAdded", "FileChanged", "WorktreeCreate", "WorktreeRemove", "PreCompact", "PostCompact",
    "PreModelSwitch", "PostModelSwitch", "Elicitation", "SessionEnd",
}
HANDLER_TYPES = {"command", "http", "mcp_tool", "prompt", "agent"}
NO_MATCHER_EVENTS = {"UserPromptSubmit", "PostToolBatch", "Stop", "TeammateIdle", "TaskCreated", "TaskCompleted"}


def hook_shape_problems(settings: dict) -> list[str]:
    """Return a list of problems with a settings dict's `hooks` block (empty list = OK).

    Documented shape: hooks -> event name -> list of matcher groups; each group has an
    optional string `matcher` and a `hooks` list of handlers; each handler has a `type`,
    and command handlers have a `command` string and an optional positive `timeout`.
    """
    problems = []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return ["top-level 'hooks' must be an object"]
    for event, groups in hooks.items():
        if event not in KNOWN_EVENTS:
            problems.append(f"unknown hook event {event!r} (check the spelling and capitalization)")
        if not isinstance(groups, list) or not groups:
            problems.append(f"{event}: must be a non-empty list of matcher groups")
            continue
        for i, group in enumerate(groups):
            where = f"{event}[{i}]"
            if not isinstance(group, dict):
                problems.append(f"{where}: matcher group must be an object")
                continue
            if "matcher" in group and not isinstance(group["matcher"], str):
                problems.append(f"{where}: matcher must be a string such as 'Edit|Write'")
            if event in NO_MATCHER_EVENTS and group.get("matcher"):
                problems.append(f"{where}: {event} doesn't support matchers, so this one is ignored")
            handlers = group.get("hooks")
            if not isinstance(handlers, list) or not handlers:
                problems.append(f"{where}: needs a non-empty 'hooks' list")
                continue
            for j, handler in enumerate(handlers):
                hw = f"{where}.hooks[{j}]"
                if not isinstance(handler, dict):
                    problems.append(f"{hw}: handler must be an object")
                    continue
                if handler.get("type") not in HANDLER_TYPES:
                    problems.append(f"{hw}: type must be one of {sorted(HANDLER_TYPES)}")
                if handler.get("type") == "command" and not isinstance(handler.get("command"), str):
                    problems.append(f"{hw}: command handlers need a 'command' string")
                if "timeout" in handler and not (
                    isinstance(handler["timeout"], (int, float)) and handler["timeout"] > 0
                ):
                    problems.append(f"{hw}: timeout must be a positive number of seconds")
    return problems


# ---------------------------------------------------------------- the settings file


def test_settings_is_valid_json_with_documented_hook_shape():
    settings = json.loads(SETTINGS.read_text())
    assert hook_shape_problems(settings) == []


def test_shape_checker_catches_common_mistakes():
    bad = {"hooks": {"postToolUse": [{"matcher": "Edit", "hooks": [{"type": "command"}]}],
                     "Stop": [{"matcher": "x", "hooks": [{"type": "command", "command": "true", "timeout": 0}]}]}}
    problems = " ".join(hook_shape_problems(bad))
    assert "unknown hook event 'postToolUse'" in problems
    assert "command handlers need a 'command' string" in problems
    assert "doesn't support matchers" in problems
    assert "timeout must be a positive number" in problems


def test_tests_run_after_edits_and_before_stopping():
    hooks = json.loads(SETTINGS.read_text())["hooks"]
    post = [g for g in hooks["PostToolUse"] if {"Edit", "Write"} <= set(g.get("matcher", "").split("|"))]
    assert post, "a PostToolUse group should match both Edit and Write"
    assert any("run_tests.py" in h["command"] for g in post for h in g["hooks"])
    assert any("run_tests.py" in h["command"] for g in hooks["Stop"] for h in g["hooks"])


def test_every_referenced_hook_script_exists():
    hooks = json.loads(SETTINGS.read_text())["hooks"]
    for groups in hooks.values():
        for group in groups:
            for handler in group["hooks"]:
                script = handler["command"].split("/.claude/hooks/")[-1].split()[0].strip('"')
                assert (FULL / ".claude" / "hooks" / script).exists(), f"missing hook script {script}"


def test_deny_rules_back_up_the_hook():
    deny = json.loads(SETTINGS.read_text())["permissions"]["deny"]
    assert "Edit(/tests/**)" in deny, "a deny rule also covers file commands Claude Code recognizes in Bash"


# ---------------------------------------------------------------- the hook scripts


def run_hook(script: str, event: dict, project_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(FULL / ".claude" / "hooks" / script)],
        input=json.dumps(event), capture_output=True, text=True, env=env, timeout=200,
    )


def test_protect_hook_blocks_test_edits_and_allows_app_edits(tmp_path):
    blocked = run_hook("protect_tests.py", {"hook_event_name": "PreToolUse", "tool_name": "Edit",
                                            "tool_input": {"file_path": str(tmp_path / "tests" / "test_pricing.py")}}, tmp_path)
    assert blocked.returncode == 2 and "protected" in blocked.stderr
    env_file = run_hook("protect_tests.py", {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / ".env")}}, tmp_path)
    assert env_file.returncode == 2
    allowed = run_hook("protect_tests.py", {"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "pricing.py")}}, tmp_path)
    assert allowed.returncode == 0 and allowed.stderr == ""


def test_run_tests_hook_reports_failures_with_exit_2(tmp_path):
    ws = make_workspace.create(tmp_path / "ws", "full", module="starter", git=False)
    result = run_hook("run_tests.py", {"hook_event_name": "Stop", "stop_hook_active": False}, ws)
    assert result.returncode == 2, "failing tests should block the stop"
    assert "failed" in result.stderr and "do not edit or skip tests" in result.stderr


def test_run_tests_hook_passes_on_the_fixed_code(tmp_path):
    ws = make_workspace.create(tmp_path / "ws", "full", module="solution", git=False)
    event = {"hook_event_name": "PostToolUse", "tool_name": "Edit", "tool_input": {"file_path": str(ws / "pricing.py")}}
    assert run_hook("run_tests.py", event, ws).returncode == 0


def test_run_tests_hook_lets_claude_stop_on_the_second_try(tmp_path):
    ws = make_workspace.create(tmp_path / "ws", "full", module="starter", git=False)
    assert run_hook("run_tests.py", {"hook_event_name": "Stop", "stop_hook_active": True}, ws).returncode == 0


# ---------------------------------------------------------------- CLAUDE.md files


@pytest.mark.parametrize("path", ["setups/memory/CLAUDE.md", "setups/full/CLAUDE.md", "templates/CLAUDE.md.template"])
def test_instruction_files_are_short_and_name_the_test_command(path):
    text = (LAB / path).read_text()
    assert len(text.splitlines()) < 200, "the memory docs recommend under 200 lines"
    assert "pytest" in text or "Run all tests" in text


# ---------------------------------------------------------------- the workspace builder


def test_workspace_hides_answers_and_rewrites_imports(tmp_path):
    ws = make_workspace.create(tmp_path / "ws", "memory", git=False)
    names = {p.relative_to(ws).as_posix() for p in ws.rglob("*") if p.is_file()}
    assert "pricing.py" in names and "tests/test_pricing.py" in names and "CLAUDE.md" in names
    assert not any("solution" in n or "holdout" in n for n in names), "the agent must not see the answers"
    assert "from pricing import" in (ws / "tests" / "test_pricing.py").read_text()


def test_bare_workspace_has_no_agent_configuration(tmp_path):
    ws = make_workspace.create(tmp_path / "ws", "bare", git=False)
    assert not (ws / "CLAUDE.md").exists() and not (ws / ".claude").exists()


def test_score_detects_tampering_and_holdout_failures(tmp_path):
    ws = make_workspace.create(tmp_path / "ws", "bare", module="starter", git=False)
    tests = ws / "tests" / "test_pricing.py"
    tests.write_text(tests.read_text().replace("== 950", "== 1000"))  # an agent "fixing" a test
    result = make_workspace.score(ws)
    assert result["tests_untouched"] is False
    assert result["holdout_failed"] > 0


def test_score_on_a_good_fix(tmp_path):
    ws = make_workspace.create(tmp_path / "ws", "full", module="solution", git=False)
    result = make_workspace.score(ws)
    assert result["tests_untouched"] is True
    assert result["visible_failed"] == 0 and result["visible_passed"] == 12
    assert result["holdout_failed"] == 0 and result["holdout_passed"] == 8
