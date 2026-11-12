#!/usr/bin/env python3
"""Merge per-week exam drafts (content-drafts/<studio>-exam-w*.json) into
src/content/exams/<studio>-exam.json. Usage: python3 scripts/assemble-exam.py s3 "Studio 3 exam: Evaluation"
"""
import glob, json, sys
studio, title = sys.argv[1], sys.argv[2]
qs = []
for f in sorted(glob.glob(f"content-drafts/{studio}-exam-w*.json")):
    d = json.load(open(f))
    d = d.get("questions", d) if isinstance(d, dict) else d
    print(f, len(d), "scenarios:", sum(q["type"] == "scenario" for q in d))
    qs += d
ids = [q["id"] for q in qs]
dups = {i for i in ids if ids.count(i) > 1}
assert not dups, f"duplicate ids: {dups}"
exam = {"id": f"{studio}-exam", "studio": studio, "title": title, "draw": 20, "timeLimitMinutes": 40, "passing": 0.8, "questions": qs}
json.dump(exam, open(f"src/content/exams/{studio}-exam.json", "w"), indent=2, ensure_ascii=False)
print("total", len(qs))
