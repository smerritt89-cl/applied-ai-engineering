"""Check code walkthroughs (src/content/walkthroughs/*.yaml) against their exercises.

    labs/.venv/bin/python scripts/check-walkthrough.py            # all
    labs/.venv/bin/python scripts/check-walkthrough.py s1-temperature s1-backoff

For each walkthrough: the matching <PyRunner id="..."> must exist in a lesson,
`code` must run and pass that exercise's hidden `tests`, note line ranges must
fit the code and cover it in order, and the shape must match the schema
(3+ notes, 2 to 4 review questions with exactly one correct option unless
type is multi). Prints one line per walkthrough; exits 1 on any failure.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WALK = ROOT / "src/content/walkthroughs"
LESSONS = ROOT / "src/content/lessons"
PY = ROOT / "labs/.venv/bin/python"


_JS_ESC = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "`": "`", "$": "$", "'": "'", '"': '"', "0": "\0"}


def js_template(raw: str) -> str:
    """Unescape a JS template literal body the way the browser does, so the tests
    we run match what the PyRunner sends to Python."""

    def repl(m: re.Match) -> str:
        e = m.group(1)
        if e.startswith("u"):
            return chr(int(e[1:].strip("{}"), 16))
        return _JS_ESC.get(e, e)

    return re.sub(r"\\(u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|.)", repl, raw, flags=re.S)


def exercises() -> dict[str, str]:
    """PyRunner id -> its tests source, from every lesson."""
    found: dict[str, str] = {}
    for mdx in LESSONS.rglob("*.mdx"):
        text = mdx.read_text()
        for block in re.findall(r"<PyRunner(.*?)</PyRunner>", text, re.S):
            m = re.search(r'\bid="([^"]+)"', block)
            if not m:
                continue
            t = re.search(r"tests=\{`(.*?)`\}", block, re.S)
            found[m.group(1)] = js_template(t.group(1) if t else "")
    return found


def check(path: pathlib.Path, ex: dict[str, str]) -> list[str]:
    errs: list[str] = []
    w = yaml.safe_load(path.read_text())
    wid = w.get("id")
    if wid != path.stem:
        errs.append(f"id {wid!r} does not match file name {path.stem!r}")
    if wid not in ex:
        errs.append(f"no <PyRunner id=\"{wid}\"> in any lesson")
    for key in ("summary", "code", "notes", "review"):
        if not w.get(key):
            errs.append(f"missing {key}")
    if errs:
        return errs
    # Types: YAML turns unquoted "a: b" into a mapping and "0.6" into a number.
    def must_str(v, where):
        if not isinstance(v, str):
            errs.append(f"{where} should be text but YAML read it as {type(v).__name__} (quote it)")
    for key in ("summary", "code"):
        must_str(w[key], key)
    for i, n in enumerate(w["notes"]):
        must_str(n.get("title"), f"notes[{i}].title")
        must_str(n.get("text"), f"notes[{i}].text")
    for q in w["review"]:
        for f in ("prompt", "explanation"):
            must_str(q.get(f), f"{q.get('id')}.{f}")
        if "code" in q:
            must_str(q["code"], f"{q.get('id')}.code")
        for o in q["options"]:
            must_str(o.get("text"), f"{q.get('id')} option {o.get('id')}.text")
            if "rationale" in o:
                must_str(o["rationale"], f"{q.get('id')} option {o.get('id')}.rationale")
    if w.get("direct"):
        for f in ("task", "prompt"):
            must_str(w["direct"].get(f), f"direct.{f}")
        for i, c in enumerate(w["direct"].get("checklist", [])):
            must_str(c, f"direct.checklist[{i}]")
    if errs:
        return errs
    code = w["code"].rstrip("\n") + "\n"
    n_lines = len(code.rstrip("\n").split("\n"))
    notes = w["notes"]
    if len(notes) < 3:
        errs.append("needs at least 3 notes")
    prev_end = 0
    for i, n in enumerate(notes):
        a, b = n["lines"]
        if not (1 <= a <= b <= n_lines):
            errs.append(f"note {i + 1} ({n['title']}) lines {a}-{b} outside 1-{n_lines}")
        if a <= prev_end:
            errs.append(f"note {i + 1} ({n['title']}) starts at {a}, overlapping or before the previous note (ended {prev_end})")
        prev_end = b
    review = w["review"]
    if not 2 <= len(review) <= 4:
        errs.append(f"review has {len(review)} questions (need 2 to 4)")
    for q in review:
        correct = sum(1 for o in q["options"] if o.get("correct"))
        if correct == 0 or (q["type"] != "multi" and correct != 1):
            errs.append(f"question {q['id']}: {correct} correct options")
        if not q["id"].startswith("wt-"):
            errs.append(f"question id {q['id']} should start with wt-")
    d = w.get("direct")
    if d and len(d.get("checklist", [])) < 2:
        errs.append("direct.checklist needs at least 2 items")
    # Run the code plus the exercise's own tests.
    tests = ex.get(wid, "")
    with tempfile.TemporaryDirectory() as tmp:
        f = pathlib.Path(tmp) / "run.py"
        f.write_text(code + "\n\n# --- exercise tests ---\n" + tests + "\n")
        r = subprocess.run([str(PY), "-I", str(f)], capture_output=True, text=True, timeout=60, cwd=tmp)
        if r.returncode != 0:
            last = (r.stderr.strip().splitlines() or ["(no output)"])[-1]
            errs.append(f"code + tests failed: {last}")
    for i, ch in enumerate(code + "".join(n["text"] for n in notes) + w["summary"]):
        if ch in "–—":
            errs.append("contains an em or en dash")
            break
    return errs


def main(ids: list[str]) -> int:
    ex = exercises()
    files = [WALK / f"{i}.yaml" for i in ids] if ids else sorted(WALK.glob("*.yaml"))
    bad = 0
    for f in files:
        if not f.exists():
            print(f"FAIL {f.stem}: file not found")
            bad += 1
            continue
        try:
            errs = check(f, ex)
        except Exception as e:  # malformed YAML and the like
            errs = [f"{type(e).__name__}: {e}"]
        print(("ok   " if not errs else "FAIL ") + f.stem + ("" if not errs else ": " + "; ".join(errs)))
        bad += bool(errs)
    if not ids:
        missing = sorted(set(ex) - {f.stem for f in files})
        if missing:
            print(f"(exercises without a walkthrough yet: {len(missing)})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
