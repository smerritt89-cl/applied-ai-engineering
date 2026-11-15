# Walkthrough: an agent-ready repo, measured

## What this code does

This lab is different from the others. Most labs hand you a module to write; this one hands a small, buggy
codebase to a **coding agent**, three times, under three different repo setups, and measures what each setup
contributes. The Python here is mostly the apparatus for that experiment: a sample application, its tests,
hidden tests the agent never sees, the setup files (`CLAUDE.md`, hooks, a reviewer subagent), and a script
that builds a clean workspace for each run and scores it afterwards.

The sample application is `starter.py`: order pricing for a small B2B storefront, with integer cents, bulk
discount tiers, promo codes, and tax. It has three seeded bugs (an off-by-one tier boundary, float rounding
that rounds half to even, and case-sensitive promo codes) that make four of its tests fail. `solution.py` is
one small, correct fix: three focused edits, no test changes, no new dependencies, every safeguard kept. It
is the standard you hold the agent's diff to, and it's the file this walkthrough tours.

Read it as a reviewer would. The interesting question in this lab is never "can an agent fix three bugs?"
(it usually can) but "did it fix them the right way, without breaking or weakening anything?" Every section
below ends with what to check in an agent's version of that code.

## How the lab fits together

Here is the flow of one run, and why each piece exists.

1. **`make_workspace.py create <folder> --setup <name>`** builds a tiny standalone repo: `pricing.py`
   (a copy of `starter.py`, bugs included), `tests/test_pricing.py` (the lab's tests with the import
   rewritten from `starter` to `pricing`), a `README.md` holding ticket #142, a `pyproject.toml`, and a
   `.gitignore`. For the `memory` and `full` setups it then copies everything in `setups/<name>/` on top.
   It finishes with `git init` and one commit, so `git diff` later shows exactly what the agent changed.
   It never copies `solution.py` or `holdout/`: an agent that can read the answers isn't being measured.
2. **You run the agent** in that folder with the same short prompt each time ("Fix ticket #142 in
   README.md."). The short prompt is deliberate: it holds your prompting constant, so differences come from
   the setup.
3. **`make_workspace.py score <folder>`** runs the workspace's own tests, then copies
   `holdout/holdout_pricing.py` in, runs it, and deletes it again (a `try`/`finally` makes sure the copy is
   removed even if pytest crashes). It also compares a SHA-256 hash of `tests/test_pricing.py` with the
   original text, so any edit to the tests, however small, shows up as `tests_untouched: false`. Finally it
   lists changed and untracked files with `git`.

The three setups are the experiment's variable:

| Setup | What the agent gets | What it tests |
|---|---|---|
| `bare` | Only the code, tests, and ticket | The agent's defaults |
| `memory` | Plus a short `CLAUDE.md`: the test command, "done means all tests pass", integer cents with half-up rounding, no new dependencies, don't edit tests, keep safeguards | What written instructions buy you |
| `full` | The same `CLAUDE.md` plus `.claude/settings.json` with hooks and deny rules, two hook scripts, and a read-only `reviewer` subagent | What enforcement buys you on top |

In the `full` setup, `protect_tests.py` is a `PreToolUse` hook on `Edit|Write`: it blocks edits under
`tests/` and to `.env` files by exiting with code 2. `run_tests.py` is registered twice: as a `PostToolUse`
hook after each edit to a `.py` file (exit code 2 can't undo the edit, but it puts the failing test output in
front of the agent right away), and as a `Stop` hook (exit code 2 sends the agent back to work). It exits 0
when the event says `stop_hook_active` is true, so it can't trap the agent in a loop. A deny rule,
`Edit(/tests/**)`, backs up the hook. The `reviewer` subagent runs on Haiku with Read, Grep, Glob and Bash
(told to use Bash only for read-only git commands) and checks the diff against a five-point list before the
agent reports done.

Two more files keep the apparatus honest. `holdout/holdout_pricing.py` has eight tests that check whether a
fix **generalizes**: the 50- and 100-unit boundaries (the visible tests only pin the 10-unit one), other promo
codes, the expiry rule surviving the case-insensitivity fix, half-up rounding inside the promo step, exact
arithmetic on a total too large for floats, and the quantity safeguard. `test_lab_setup.py` checks the
infrastructure itself: that `settings.json` has the documented hooks shape, that the hook scripts block and
allow what they should, that the `CLAUDE.md` files are short and name a test command, and that the
workspace builder hides the answers and the scorer catches tampering.

## How to read this lab

Open `work.py` beside this page. It starts as an exact copy of `solution.py` (made by
`python lab.py review all`), so every line reference below matches it until you change it. Keep `starter.py`
open too, or run `diff starter.py solution.py` in a terminal: the three edits are the heart of the lab.

Run the tests from VS Code's **Testing** panel (the flask icon), or from the `labs` folder with
`pytest electives/e2-agent-ready-repo -q`. While `work.py` exists, `test_pricing.py` imports it instead of
`starter.py`, so you'll see **28 passed** (plus 12 skipped: the `CHANGE.md` tests, which only run when you
ask for `test_change.py` by name) rather than the README's "4 failed, 24 passed". That's expected:
you're reviewing the fixed code. (`python lab.py reset electives/e2-agent-ready-repo` brings back the failing
version.) `work.py` has no effect on the agent runs: `make_workspace.py` always copies `starter.py` into a
workspace, and the infrastructure tests in `test_lab_setup.py` read `starter.py` and `solution.py` directly.

## The module docstring and imports (lines 1 to 19)

```python
Rules the business agreed on (see the ticket in the workspace README):

- All money is integer cents. Never use floats for money.
- Bulk discount by quantity on each line: 10 or more units 5% off, 50 or more 10%,
  100 or more 15%. The discount is rounded half up to the nearest cent.
```

The docstring at the top of a module is its first piece of documentation, and here it's also the **spec**.
The workspace README tells the agent "the business rules are in the docstring at the top of `pricing.py`",
and the `CLAUDE.md` in both configured setups says to read it before changing behavior. So when you review an
agent's change, check it against these four bullets, not just against the tests. (In `starter.py` the
docstring says the same rules; only the opening lines that describe the file differ.)

`from __future__ import annotations` (line 16) makes Python treat type hints as text instead of evaluating
them when the function is defined. It lets newer hint syntax such as `str | None` work on older Python
versions and avoids ordering problems between classes. `dataclass` and `date` come from the standard
library; the module needs nothing else, which is one of the rules ("don't add dependencies").

**What to check:** an agent change that alters behavior should update this docstring in the same diff. A
docstring and code that disagree after a change mean one of them is wrong.

## Bulk tiers and promo codes as data (lines 21 to 28)

```python
# (minimum quantity, percent off), checked from the largest tier down
BULK_TIERS = [(100, 15), (50, 10), (10, 5)]

PROMO_CODES = {
    "WELCOME10": {"percent": 10, "expires": date(2027, 1, 31)},
```

`BULK_TIERS` is a list of **tuples**, each `(minimum quantity, percent off)`. `PROMO_CODES` is a **dict of
dicts**: each code maps to its percent and an expiry date, where `None` means "never expires". Keeping the
business numbers in data structures at the top, rather than scattered through `if` statements, means a price
change is a one-line edit a reviewer can verify at a glance.

The comment on the tiers matters. The lookup below returns the **first** tier that matches, so the list must
run from largest to smallest. If it ran `[(10, 5), (50, 10), (100, 15)]`, a 100-unit order would match the
10-unit tier first and get 5% instead of 15%.

Note that the keys of `PROMO_CODES` are all uppercase. That's what makes the case-insensitivity fix in
`promo_percent` work.

**What to check:** an agent that "fixes" the 10-unit bug by adding a new tier, or by reordering this list,
has changed the business rules. The fix belongs in the comparison, not the data.

## `PricingError` and `LineItem` (lines 31 to 39)

```python
class PricingError(ValueError):
    """Raised for invalid input or a promo code that can't be applied."""


@dataclass(frozen=True)
class LineItem:
    sku: str
    quantity: int
    unit_price_cents: int
```

`PricingError(ValueError)` defines a **custom exception** that inherits from the built-in `ValueError`. The
class body is just a docstring, which is enough: the class exists to have a name. Callers can catch
`PricingError` specifically (the checkout page shows "invalid promo code"), and code that already catches
`ValueError` still works. The tests rely on it: `pytest.raises(PricingError, match="expired")` checks both
the type and the message.

`@dataclass(frozen=True)` is a **decorator** that writes the boring parts of a class for you: an `__init__`
that takes `sku`, `quantity` and `unit_price_cents`, a readable `repr`, and equality. The **type hints**
(`sku: str`) declare the fields. `frozen=True` makes instances immutable: `item.quantity = 5` raises an
error. A line item that can't change after it's created can't be modified halfway through a price
calculation by accident.

Type hints are not enforced at runtime. `LineItem("PEN", 1, -5)` creates a line with a negative price
without complaint, which is why the checks in `line_total_cents` exist.

## `percent_of` (lines 42 to 46): the rounding fix

```python
def percent_of(amount_cents: int, percent: int) -> int:
    """Return percent% of amount_cents, rounded half up to a whole cent."""
    # Integer arithmetic: exact for any size, and +50 makes .5 round up.
    # (round() on a float rounds half to even and loses precision on big totals.)
    return (amount_cents * percent + 50) // 100
```

This is the subtlest of the three fixes, and the one agents most often get half right. The buggy version was
`int(round(amount_cents * percent / 100))`, which has two separate problems.

- **Half to even.** Python's `round()` uses "banker's rounding": exact halves go to the nearest even number.
  `round(24.5)` is `24`, and `round(0.5)` is `0`. The business rule is half up, so 14 clips at 35 cents
  (490 cents, 5% off is 24.5 cents) must take 25 cents off, not 24. That's the visible test
  `test_bulk_discount_rounds_half_up`.
- **Float precision.** `/` always produces a float, and a float can represent every whole number exactly
  only up to about 9 quadrillion (2 to the 53rd power). The holdout test with 100 units at 900,719,925,474,091
  cents goes past that, and the float version comes out one cent off.

The fix stays in integers throughout. `amount_cents * percent` is the discount in hundredths of a cent;
adding 50 (half of 100) and then **floor dividing** with `//` (divide and drop the remainder) rounds half up.
Worked value: `(490 * 5 + 50) // 100` is `2500 // 100`, which is 25. Python integers have no size limit, so
this is exact for any order.

Every percentage in the module (bulk, promo, tax) goes through this one function. That's why one fix
repaired two failing tests: the bulk rounding test and `test_tax_rounds_half_up` (1% of 650 cents is 6.5,
which must become 7).

The two-line comment explains *why* the code looks unusual. Without it, a future cleanup (by a person or an
agent) might "simplify" it back to `round()`.

**What to check:** look for any `/` or `round(` in money code. A common agent fix is
`int(amount_cents * percent / 100 + 0.5)`: it rounds half up and passes every visible test, but it's still
float arithmetic, and it fails the large-order holdout. Also check that the fix is in `percent_of`, not
patched separately into each caller.

## `bulk_discount_percent` (lines 49 to 54): the boundary fix

```python
def bulk_discount_percent(quantity: int) -> int:
    """Percent off for a line with this many units."""
    for min_quantity, percent in BULK_TIERS:
        if quantity >= min_quantity:
            return percent
    return 0
```

The loop **unpacks** each tuple into two names (`for min_quantity, percent in ...`) and returns the first
tier the quantity reaches. If none matches, the loop ends and the function returns 0. Returning from inside
a loop like this is a clean way to say "first match wins".

The fix is one character: `>` became `>=`. The rule says "10 **or more** units", and the buggy `>` meant 10
units got nothing (the customer in ticket #142). The same character fixed the 50 and 100 boundaries at the
same time, because they all share this comparison.

**What to check:** this is where overfitting shows up. An agent that special-cases the visible test
(`if quantity == 10: return 5`) passes `test_bulk_discount_starts_at_ten_units` and fails the holdout's
50- and 100-unit tests. A one-character fix to the shared comparison is what generalizing looks like.

## `line_total_cents` (lines 57 to 64)

```python
    if item.quantity <= 0:
        raise PricingError(f"quantity must be positive for {item.sku}")
    if item.unit_price_cents < 0:
        raise PricingError(f"price must not be negative for {item.sku}")
    gross = item.quantity * item.unit_price_cents
    return gross - percent_of(gross, bulk_discount_percent(item.quantity))
```

Two **guard clauses** come first: check for bad input and raise before doing any work. The messages are
**f-strings**: `{item.sku}` is replaced by the product code, so an error says which line of the order was
wrong. Note the asymmetry: quantity must be positive (zero is an error), but price may be zero (free
samples are allowed, and the holdout checks that).

Then the arithmetic: gross price, minus the bulk discount computed on the gross. Every value is an `int`,
so the result is an `int`.

This function didn't change between `starter.py` and `solution.py`. That's the point: the bugs were
elsewhere, and a good fix leaves correct code alone.

**What to check:** these guards are "safeguards" in the lab's language. An agent chasing failing tests
sometimes removes or loosens a check that's in its way. Both `CLAUDE.md` files say to keep safeguards,
`test_rejects_non_positive_quantity` and `test_rejects_negative_price` cover them, and the holdout checks
the quantity guard again.

## `promo_percent` (lines 67 to 75): the case-insensitivity fix

```python
    promo = PROMO_CODES.get(code.strip().upper())
    if promo is None:
        raise PricingError(f"unknown promo code: {code!r}")
    expires = promo["expires"]
    if expires is not None and today > expires:
        raise PricingError(f"promo code {code!r} expired on {expires.isoformat()}")
    return promo["percent"]
```

`code.strip().upper()` **chains two string methods**: `strip()` removes surrounding whitespace and `upper()`
capitalizes, so `"welcome10 "` becomes `"WELCOME10"`, which matches the uppercase key. `PROMO_CODES.get(...)`
uses **dict.get**, which returns `None` for a missing key instead of raising `KeyError`; the next line turns
that into a clear `PricingError`.

`{code!r}` in the f-string uses the **`!r` conversion**: it shows the value as Python would write it, with
quotes, so a message reads `unknown promo code: 'welcome10 '`. The quotes make stray whitespace visible,
which is exactly what support needs when a customer says "my code didn't work".

The expiry check comes after the lookup and uses `today > expires`, so a code is still valid on its expiry
date. `None` means no expiry, and the `expires is not None and ...` order matters: `and` stops at the first
false value (**short-circuit evaluation**), so `today > None` is never evaluated (it would raise
`TypeError`).

**What to check:** the safeguard most at risk in this ticket is the expiry check. An agent making codes
case-insensitive can restructure this function and lose it, or fix only `WELCOME10`. The holdout tests
`test_other_codes_are_case_insensitive_too` and `test_case_insensitivity_does_not_bypass_expiry` exist for
exactly those two failure modes. Also watch for a fix that lowercases the dict keys instead: it can work, but
it's a bigger change than needed and every other place that names a code has to change too.

## `order_total_cents` (lines 78 to 91)

```python
def order_total_cents(
    items: list[LineItem],
    promo_code: str | None = None,
    tax_rate_percent: int = 0,
    today: date | None = None,
) -> int:
    ...
    today = today or date.today()
    subtotal = sum(line_total_cents(item) for item in items)
    if promo_code:
        subtotal -= percent_of(subtotal, promo_percent(promo_code, today))
    return subtotal + percent_of(subtotal, tax_rate_percent)
```

The signature spreads its parameters over several lines, one per parameter, which is the readable style for
long signatures. `list[LineItem]` and `str | None` are **type hints**: "a list of line items" and "a string
or `None`". Three parameters have **default values**, so the simplest call is `order_total_cents(items)`.

Why `today: date | None = None` and then `today = today or date.today()`, instead of `today=date.today()`
in the signature? Because Python evaluates default values **once**, when the function is defined. A default
of `date.today()` would freeze the date at the moment the module was imported, and a server running for a
week would keep using last week's date for expiry checks. The `None` default plus the line inside the
function gets the real date on every call. It also lets tests pass a fixed `today`, which is why the tests
use `TODAY = date(2026, 11, 11)` and don't break when the calendar moves on.

The body applies the rules in the docstring's order: an empty order is rejected; line totals are summed
with a **generator expression** inside `sum`; the promo comes off the subtotal (after bulk discounts); tax
applies to the discounted subtotal. Each step rounds separately, through `percent_of`.

`if promo_code:` treats both `None` and the empty string as "no promo". A code of only spaces is truthy,
so it reaches `promo_percent`, strips to `""`, and is rejected as unknown, which is reasonable.

**What to check:** the order of operations is business logic. An agent that applies tax before the promo,
or the promo to each line separately, can still pass a test or two and be wrong by cents on real orders.
`test_order_with_promo_and_tax` pins the order on one example, and the holdout's
`test_half_cent_rounds_up_in_promo` pins rounding inside the promo step.

## What the tests check

**`test_pricing.py` (12 tests, the sample repo's own suite).**

- *Bulk discounts:* no discount at 9 units, 5% starting at exactly 10, the 50-unit tier at 60 units, and
  half-up rounding on the bulk discount. Two of these fail on `starter.py`.
- *Promo codes:* a lowercase code with a trailing space is accepted (fails on `starter.py`), an expired code
  is rejected, an unknown code is rejected.
- *Whole orders:* promo plus tax on a two-line order, and half-up rounding on tax (fails on `starter.py`).
- *Safeguards:* zero quantity, negative price, and an empty order all raise `PricingError`.

**`holdout/holdout_pricing.py` (8 tests, never shown to the agent).** Exactly 50 and exactly 100 units, a
different code in mixed case with leading spaces, an expired code in lowercase, half-up rounding in the
promo step, exact rounding on a total beyond float precision, a zero price, and a negative quantity. They
exist because the visible tests only pin one point of each rule, and an agent that optimizes for green tests
can satisfy those points without implementing the rule.

**`test_lab_setup.py` (16 tests, the lab's own infrastructure).** The hooks block in `settings.json` has the
documented shape (with a checker that is itself tested on a deliberately broken config), `PostToolUse` and
`Stop` both run the tests, every referenced hook script exists, and the deny rule is present. The hook
scripts are run as real subprocesses with JSON on stdin: the protect hook blocks a test edit and a `.env`
write and allows an application edit; the test hook exits 2 on failing code, 0 on fixed code, and 0 when
`stop_hook_active` is true. The `CLAUDE.md` files are under 200 lines and name a test command. The
workspace builder hides `solution.py` and `holdout/`, rewrites the import, and adds no agent configuration
to a bare workspace; the scorer flags an edited test and passes the reference fix on all 20 tests.

**What they don't check.** Nothing here runs an agent; the agent runs are the experiment, and you score
them. The tests don't check whether a fix is minimal (that's your `git diff` review), whether dependencies
were added, or whether the agent's final report was honest about what it ran. The hook tests check the
scripts' logic, not that Claude Code actually loads `settings.json` the way the lab expects; the README
points you to the hooks guide for that. And the tamper check only covers `tests/test_pricing.py`: an agent
that added a `conftest.py` that skips tests would not be caught by the hash comparison, and since the
holdout file is copied into the same workspace, it could be affected too. The new file would appear in
`files_changed`, which is one reason to read that list on every run.

## Review questions

1. An agent's fix for the rounding bug is `return int(amount_cents * percent / 100 + 0.5)`. Does it pass
   the visible tests? What does `score` report?

<details>
<summary>Answer</summary>

It passes all 12 visible tests: it rounds 24.5 up to 25 and 6.5 up to 7. But it is still float arithmetic,
so `test_exact_rounding_on_very_large_totals` in the holdout fails by one cent: `score` reports
`holdout_failed: 1`. This is the lab's core lesson in one line: passing tests is necessary, not sufficient,
and the `CLAUDE.md` rule "never use floats or `round()` for money" exists to prevent exactly this.

</details>

2. Why does `BULK_TIERS` run from 100 down to 10, and what would happen to a 120-unit order if an agent
   sorted it ascending?

<details>
<summary>Answer</summary>

`bulk_discount_percent` returns the first tier the quantity reaches. Sorted ascending, a 120-unit order
would match `(10, 5)` first and get 5% instead of 15%. The visible tests wouldn't catch it (none uses 100
or more units); the holdout's 100-unit test would.

</details>

3. Why does `order_total_cents` take `today=None` rather than `today=date.today()`?

<details>
<summary>Answer</summary>

Default values are evaluated once, when the function is defined. `date.today()` as a default would freeze
the date at import time, so a long-running server would check promo expiry against a stale date. `None`
plus `today = today or date.today()` gets the current date on each call, and still lets tests pass a fixed
date.

</details>

4. In a `bare` run, the agent edits `tests/test_pricing.py` to change `== 950` to `== 1000` and reports
   "all tests pass". Which part of the lab catches it, and which part of the `full` setup would have stopped
   it?

<details>
<summary>Answer</summary>

`score` compares a SHA-256 hash of the test file with the original and reports `tests_untouched: false`
(and prints a warning), and `git diff` shows the edited line. In the `full`
setup, the `PreToolUse` hook `protect_tests.py` blocks `Edit` and `Write` calls on `tests/`, and the deny
rule `Edit(/tests/**)` backs it up. `test_lab_setup.py` checks both are in place.

</details>

5. Why does `make_workspace.py` never copy `solution.py` or `holdout/` into a workspace, and why does
   `score` delete its holdout copy in a `finally` block?

<details>
<summary>Answer</summary>

An agent explores the folder it runs in. If the answers or the hidden tests were there, it could read them,
and you'd be measuring its ability to copy, not to fix. The `finally` block removes the holdout copy even if
pytest crashes, so a workspace you score twice (or keep using) never ends up containing the hidden tests.
`test_workspace_hides_answers_and_rewrites_imports` checks the first part.

</details>
