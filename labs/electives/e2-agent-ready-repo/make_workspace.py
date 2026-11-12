"""Create a fresh workspace for an agent run, and score the result afterwards.

    python make_workspace.py create ~/agent-runs/bare-1 --setup bare
    python make_workspace.py create ~/agent-runs/full-1 --setup full
    python make_workspace.py score ~/agent-runs/full-1

A workspace is a tiny standalone repo: pricing.py (copied from starter.py),
tests/test_pricing.py, a README with the ticket, and whatever the chosen setup adds
(CLAUDE.md, hooks, a reviewer subagent). It never contains solution.py or the
holdout tests, so the agent can't read the answers. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent
SETUPS = ("bare", "memory", "full")

TICKET = """# Order pricing service

Ticket #142 (from support):

> A customer ordered exactly 10 binders and was charged full price, but our pricing page
> says 10 or more units get 5% off. They also typed their promo code as "welcome10 " and
> checkout rejected it. Finance adds that some totals are off by a cent.

The business rules are in the docstring at the top of `pricing.py`.
The tests are in `tests/`. Fix the bugs so the tests pass.
"""

PYPROJECT = """[project]
name = "order-pricing"
version = "0.1.0"
requires-python = ">=3.10"

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
"""


def workspace_tests_text() -> str:
    """The lab's test file as it appears in a workspace (importing `pricing`)."""
    text = (LAB / "test_pricing.py").read_text()
    # (solution is accepted too, so the lab's "switch the import" check works)
    return text.replace("from starter import", "from pricing import").replace("from solution import", "from pricing import")


def create(dest: Path, setup: str = "bare", module: str = "starter", git: bool = True) -> Path:
    """Build a workspace at dest. `module` picks the source of pricing.py (the tests use "solution")."""
    if setup not in SETUPS:
        raise ValueError(f"setup must be one of {SETUPS}, not {setup!r}")
    if module not in ("starter", "solution"):
        raise ValueError("module must be 'starter' or 'solution'")
    dest = Path(dest).expanduser().resolve()
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"{dest} exists and is not empty; pick a new folder for each run")
    (dest / "tests").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(LAB / f"{module}.py", dest / "pricing.py")
    (dest / "tests" / "test_pricing.py").write_text(workspace_tests_text())
    (dest / "README.md").write_text(TICKET)
    (dest / "pyproject.toml").write_text(PYPROJECT)
    (dest / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n.claude/settings.local.json\nCLAUDE.local.md\n")
    if setup != "bare":
        shutil.copytree(LAB / "setups" / setup, dest, dirs_exist_ok=True)
    if git and shutil.which("git"):
        run = lambda *args: subprocess.run(["git", *args], cwd=dest, capture_output=True, text=True)
        run("init", "-q")
        run("add", "-A")
        run("-c", "user.name=lab", "-c", "user.email=lab@example.com", "commit", "-q", "-m", f"Starting point ({setup} setup)")
    return dest


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _pytest(target: str, cwd: Path) -> tuple[int, int, str]:
    """Run pytest on target inside cwd. Returns (passed, failed, tail of output)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", target],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=300,
        env={**_clean_env(), "PYTHONPATH": str(cwd)},
    )
    out = proc.stdout + proc.stderr
    passed = failed = 0
    for line in out.splitlines()[-5:]:
        words = line.replace(",", " ").split()
        for i, word in enumerate(words[1:], start=1):
            if word in ("passed", "failed", "error", "errors") and words[i - 1].isdigit():
                if word == "passed":
                    passed = int(words[i - 1])
                else:
                    failed += int(words[i - 1])
    return passed, failed, "\n".join(out.strip().splitlines()[-15:])


def _clean_env() -> dict:
    import os

    return {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}


def score(workspace: Path) -> dict:
    """Check an agent's finished workspace: visible tests, holdout tests, and test tampering."""
    workspace = Path(workspace).expanduser().resolve()
    tests_file = workspace / "tests" / "test_pricing.py"
    tests_untouched = tests_file.exists() and _sha(tests_file.read_text()) == _sha(workspace_tests_text())
    vis_pass, vis_fail, _ = _pytest("tests", workspace)
    holdout_copy = workspace / "test_holdout_check.py"
    shutil.copyfile(LAB / "holdout" / "holdout_pricing.py", holdout_copy)
    try:
        hold_pass, hold_fail, hold_tail = _pytest(holdout_copy.name, workspace)
    finally:
        holdout_copy.unlink(missing_ok=True)
    changed = []
    if shutil.which("git") and (workspace / ".git").exists():
        diff = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=workspace, capture_output=True, text=True)
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"], cwd=workspace, capture_output=True, text=True
        )
        changed = sorted(set(diff.stdout.split()) | set(untracked.stdout.split()))
    return {
        "workspace": str(workspace),
        "visible_passed": vis_pass,
        "visible_failed": vis_fail,
        "holdout_passed": hold_pass,
        "holdout_failed": hold_fail,
        "tests_untouched": tests_untouched,
        "files_changed": changed,
        "holdout_output": hold_tail,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="make a fresh workspace")
    c.add_argument("dest")
    c.add_argument("--setup", choices=SETUPS, default="bare")
    s = sub.add_parser("score", help="score a finished workspace")
    s.add_argument("workspace")
    args = parser.parse_args(argv)
    if args.cmd == "create":
        path = create(Path(args.dest), args.setup)
        print(f"Workspace ready at {path} ({args.setup} setup). cd there and start your agent.")
        return 0
    result = score(Path(args.workspace))
    print(json.dumps({k: v for k, v in result.items() if k != "holdout_output"}, indent=2))
    if result["holdout_failed"]:
        print("\nHoldout failures (the fix didn't generalize):\n" + result["holdout_output"])
    if not result["tests_untouched"]:
        print("\nWARNING: tests/test_pricing.py was modified. Read that diff first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
