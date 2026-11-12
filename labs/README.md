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
