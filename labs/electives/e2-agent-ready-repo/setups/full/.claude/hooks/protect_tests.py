#!/usr/bin/env python3
"""Claude Code PreToolUse hook: block edits to the test suite and to secrets.

Exit code 2 on a PreToolUse hook blocks the tool call, and Claude sees our stderr
as the reason. Exit 0 means "no objection" and the normal permission flow applies.

Limits worth knowing (see lesson e2-w3-l7): this hook only sees the tools its
matcher names (Edit|Write). A shell command such as `sed -i` or a Python script
can still change a test file, so pair it with a deny rule, the sandbox, and a CI
check that compares test files against the base branch.
"""
from __future__ import annotations

import json
import os
import sys

PROTECTED_DIRS = ("tests",)
PROTECTED_NAMES = (".env",)


def is_protected(file_path: str, project_dir: str) -> bool:
    if not file_path:
        return False
    rel = os.path.relpath(os.path.realpath(file_path), os.path.realpath(project_dir))
    parts = rel.replace("\\", "/").split("/")
    if parts[0] in PROTECTED_DIRS:
        return True
    return os.path.basename(rel) in PROTECTED_NAMES


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    file_path = str((event.get("tool_input") or {}).get("file_path", ""))
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    if is_protected(file_path, project_dir):
        print(
            f"Blocked: {file_path} is protected. The tests are the contract for this task. "
            "If you believe a test is wrong, stop and explain why to the user instead of editing it.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
