"""Check a lab's review-track files (for authors).

    .venv/bin/python check_change.py studio-1/01-first-call

Verifies, in a temporary copy of the labs folder:
  1. the lab's main tests pass against solution.py;
  2. test_change.py exists, every test in it is marked `change`, and they FAIL
     against solution.py (the change isn't already there);
  3. they PASS against change_solution.py, and the main tests still pass too
     (the change didn't break anything);
  4. WALKTHROUGH.md and CHANGE.md exist, and every "(lines A to B)" reference
     in WALKTHROUGH.md fits within solution.py.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).parent
PY = HERE / ".venv/bin/python"


def pytest(cwd: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(PY), "-m", "pytest", "-q", "-p", "no:cacheprovider", *args], cwd=cwd, capture_output=True, text=True, timeout=300)


def main(lab_arg: str) -> int:
    lab = (HERE / lab_arg).resolve()
    rel = lab.relative_to(HERE)
    problems: list[str] = []
    for name in ("WALKTHROUGH.md", "CHANGE.md", "test_change.py", "change_solution.py", "solution.py"):
        if not (lab / name).exists():
            problems.append(f"missing {name}")
    if problems:
        print("FAIL", rel, "; ".join(problems))
        return 1
    sol_lines = len((lab / "solution.py").read_text().splitlines())
    for a, b in re.findall(r"lines? (\d+)(?: to (\d+))?", (lab / "WALKTHROUGH.md").read_text()):
        if int(b or a) > sol_lines:
            problems.append(f"WALKTHROUGH.md cites line {b or a}, but solution.py has {sol_lines} lines")
    tc = (lab / "test_change.py").read_text()
    n_tests = len(re.findall(r"^def test_", tc, re.M))
    if n_tests == 0:
        problems.append("test_change.py has no tests")
    if "pytest.mark.change" not in tc:
        problems.append("test_change.py tests are not marked @pytest.mark.change (use pytestmark = pytest.mark.change)")
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        for f in ("conftest.py", "pytest.ini"):
            shutil.copy(HERE / f, root / f)
        dst = root / rel
        shutil.copytree(lab, dst, ignore=shutil.ignore_patterns("work.py", "__pycache__", ".venv"))
        shutil.copy(lab / "solution.py", dst / "work.py")
        r = pytest(root, str(rel))
        if r.returncode != 0:
            problems.append("main tests fail against solution.py: " + r.stdout.strip().splitlines()[-1])
        r = pytest(root, str(rel / "test_change.py"))
        if r.returncode == 0 or "failed" not in r.stdout:
            problems.append("test_change.py should FAIL against solution.py, got: " + r.stdout.strip().splitlines()[-1])
        shutil.copy(lab / "change_solution.py", dst / "work.py")
        r = pytest(root, str(rel / "test_change.py"))
        if r.returncode != 0:
            problems.append("test_change.py should PASS against change_solution.py, got: " + r.stdout.strip().splitlines()[-1])
        r = pytest(root, str(rel))
        if r.returncode != 0:
            problems.append("main tests should still pass against change_solution.py, got: " + r.stdout.strip().splitlines()[-1])
    text = "".join((lab / f).read_text() for f in ("WALKTHROUGH.md", "CHANGE.md"))
    if "—" in text or "–" in text:
        problems.append("WALKTHROUGH.md or CHANGE.md contains an em or en dash")
    print(("ok  " if not problems else "FAIL"), rel, ("" if not problems else "\n  - " + "\n  - ".join(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
