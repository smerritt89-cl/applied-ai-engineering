# Labs

Hands-on exercises that can't run in the browser: they call real model APIs,
read local files, or need packages Pyodide doesn't have. Each lab is a folder
with a `README.md` (the task), a `starter.py` (your code goes here), and
`test_*.py` (the checks).

## One-time setup

```bash
cd labs
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then paste your API key into .env
```

## Two tracks

**Review track (default).** The course is built around reading, judging, and directing
code, much of it AI-written, more than typing it from scratch. For each lab:

1. Run `python lab.py review all` once. It copies each lab's `solution.py` to `work.py`,
   your own copy (gitignored). While `work.py` exists, that lab's tests run against it.
2. Open the lab in VS Code (the **Open in VS Code** button on the lesson page) and read
   `WALKTHROUGH.md`: a guided tour of the code, section by section, and what the tests check.
3. Run the tests from VS Code's **Testing** panel (flask icon). They should all pass.
4. Do `CHANGE.md`: ask a coding assistant (Claude Code, for example) to make a specific
   change to `work.py`, review what it did against the checklist, then run
   `test_change.py`, which passes only when the change is right.

**Write track (optional).** `python lab.py reset <lab>` removes `work.py`; the tests go
back to `starter.py`, and you implement it yourself using the steps in the lab's README.

## VS Code

Open the `labs` folder itself in VS Code (not the whole repo): `code labs`. The
settings in `labs/.vscode/` select the lab Python environment, put the tests in the
Testing panel, and open Markdown files as formatted pages.

## Running a lab

```bash
source .venv/bin/activate
pytest studio-1/01-first-call -q
```

Offline tests check the logic you write (parsing, validation, cost math) with
no API calls. Tests marked `live` call the real API and are skipped until
`ANTHROPIC_API_KEY` is set in `.env`. A full studio's live tests cost well under
a dollar on current pricing; each lab README states the expected cost.

Stuck? Each lab has a `solution.py`. Try for 20 minutes first.

Keys stay in `labs/.env`, which is gitignored. Never paste a key into a lesson
page, a notebook you commit, or a prompt.
