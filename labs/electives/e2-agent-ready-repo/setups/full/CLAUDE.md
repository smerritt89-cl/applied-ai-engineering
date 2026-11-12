# Commands
- Run all tests: `python3 -m pytest -q`
- Run one test: `python3 -m pytest -q tests/test_pricing.py -k <name>`

# Done means
- All tests pass. Show the pytest command and its last lines of output when you say you're done.

# Conventions that differ from the defaults
- Money is integer cents everywhere. Never use floats or `round()` for money: Python's `round()` rounds half to even, and the business rule is half up.
- Business rules live in the docstring at the top of `pricing.py`. Read it before changing behavior.

# Boundaries
- Don't add dependencies; this repo uses the standard library plus pytest.
- Don't edit, skip, or delete tests to make them pass. If a test looks wrong, stop and explain why.
- Keep safeguards (input validation, promo expiry checks) unless the ticket says to change them.

# Checks that run automatically (see .claude/settings.json)
- After every edit to a Python file, a hook runs the tests and shows you any failures.
- Edits to `tests/` are blocked. A Stop hook runs the tests before you finish.
- Before you summarize, ask the `reviewer` subagent to review the diff against the ticket in README.md.
