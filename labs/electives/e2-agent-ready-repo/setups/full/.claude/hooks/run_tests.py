#!/usr/bin/env python3
"""Claude Code hook: run the test suite and report failures back to Claude.

Registered twice in .claude/settings.json:

- PostToolUse on Edit|Write: after each edit to a Python file. Exit code 2 on a
  PostToolUse hook can't undo the edit (the tool already ran); it shows our stderr
  to Claude, so the failing output lands in its context right away.
- Stop: when Claude tries to finish its turn. Exit code 2 on a Stop hook blocks
  the stop and sends Claude back to work with our stderr as the reason.

Hooks receive the event as JSON on stdin. Following the hooks guide, the Stop
branch exits 0 when `stop_hook_active` is true, which means Claude is already
continuing because of a Stop hook; that prevents an endless loop. (Claude Code
also caps consecutive Stop-hook blocks.) Check the current hooks reference before
relying on any field: https://code.claude.com/docs/en/hooks
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

MAX_LINES = 40  # keep what we send to Claude short: it all lands in the context window


def read_event() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def should_run(event: dict) -> bool:
    name = event.get("hook_event_name", "")
    if name == "Stop":
        return not event.get("stop_hook_active", False)
    if name == "PostToolUse":
        path = str((event.get("tool_input") or {}).get("file_path", ""))
        return path.endswith(".py")
    return True  # run manually or from another event: just run the tests


def run_tests(project_dir: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", "tests"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=110,
    )
    lines = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode, "\n".join(lines[-MAX_LINES:])


def main() -> int:
    event = read_event()
    if not should_run(event):
        return 0
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    code, output = run_tests(project_dir)
    if code == 0:
        return 0
    print(
        "The test suite is failing. Fix the application code; do not edit or skip tests "
        "without asking the user first.\n" + output,
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
