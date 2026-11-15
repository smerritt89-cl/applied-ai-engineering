"""Lab helper: set up the review track for one lab or all of them.

    python lab.py review studio-1/01-first-call   # copy solution.py to work.py
    python lab.py review all                      # every lab
    python lab.py reset studio-1/01-first-call    # delete work.py (back to starter.py)
    python lab.py status                          # which labs have a work.py

work.py is your copy to read, run, and change (for CHANGE.md tasks). It is
gitignored, so it never conflicts with course updates. While it exists, the
lab's tests run against it instead of starter.py (see conftest.py).
"""
from __future__ import annotations

import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).parent


def labs() -> list[pathlib.Path]:
    return sorted(p.parent for p in HERE.glob("*/*/solution.py") if ".venv" not in p.parts)


def resolve(arg: str) -> list[pathlib.Path]:
    if arg == "all":
        return labs()
    lab = (HERE / arg.removeprefix("labs/")).resolve()
    if not (lab / "solution.py").exists():
        sys.exit(f"No lab at {lab} (expected a solution.py there).")
    return [lab]


def main(argv: list[str]) -> None:
    if not argv or argv[0] not in {"review", "reset", "status"}:
        sys.exit(__doc__)
    cmd = argv[0]
    if cmd == "status":
        for lab in labs():
            mark = "work.py" if (lab / "work.py").exists() else "starter.py"
            print(f"{lab.relative_to(HERE)}: tests use {mark}")
        return
    if len(argv) < 2:
        sys.exit(f"Usage: python lab.py {cmd} <lab folder | all>")
    for lab in resolve(argv[1]):
        work = lab / "work.py"
        name = lab.relative_to(HERE)
        if cmd == "review":
            if work.exists():
                print(f"{name}: work.py already exists, left as is (reset first to start over)")
            else:
                shutil.copyfile(lab / "solution.py", work)
                print(f"{name}: created work.py from solution.py")
        else:
            if work.exists():
                work.unlink()
                print(f"{name}: removed work.py; tests use starter.py again")


if __name__ == "__main__":
    main(sys.argv[1:])
