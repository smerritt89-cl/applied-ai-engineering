# Change: cap how much a promo code can take off

This is the review-track exercise for this lab. The rest of the lab measures agents working on a repo you
set up; here **you** direct a coding assistant on a small change, using the same habits the setups try to
build in: a clear spec, hard boundaries, and evidence before "done".

The work happens in `work.py` in this lab folder (your copy of `solution.py`), not in an `~/agent-runs`
workspace. `make_workspace.py` always copies `starter.py`, so nothing you change here affects the agent
comparison runs.

## The change

Ticket #151, from Marketing: WELCOME10 is meant for small first orders, but a reseller used it on a
1,000-dollar bulk order and got 85 dollars off. From now on, WELCOME10 takes at most **25.00 dollars
(2500 cents)** off an order. Other codes are uncapped for now, but Marketing wants to be able to cap any code
later without a code change.

Concretely:

- Each entry in `PROMO_CODES` gets a `max_off_cents` key: an integer number of cents, or `None` for no cap.
  WELCOME10 gets 2500; SPRING5 and VIP20 get `None`.
- The promo discount is still the code's percent of the subtotal, rounded half up with `percent_of`, and is
  then capped at `max_off_cents`. Tax still applies to the subtotal after the (capped) promo.
- The cap is read from the data. Nothing may special-case the string `"WELCOME10"` in code.
- Everything else stays the same: unknown and expired codes are still rejected, codes are still
  case-insensitive and trimmed, `promo_percent` still returns the percent, and all money stays integer cents.

Worked example: 100 binders at 10.00 dollars is 100,000 cents gross, 85,000 after the 15% bulk tier.
WELCOME10's 10% would be 8,500 cents; the cap brings it to 2,500, so the total before tax is 82,500 cents.

## Write your prompt

Write your own prompt for a coding assistant (Claude Code, for example, opened on the `labs` folder) before
you look at the example. This lab is about what a repo setup gives an agent, so notice that here **your
prompt has to do the job of the `CLAUDE.md`**: the agent working in this folder doesn't get the lab's
`setups/` files. A good prompt for this change:

- names the file to change (`work.py`) and the files it must not touch (`test_pricing.py`, `solution.py`,
  `starter.py`, anything under `setups/` or `holdout/`);
- states the rule precisely, including the data shape (`max_off_cents`, `None` for no cap) and where the cap
  applies (after the percent and rounding, before tax);
- restates the repo's conventions: integer cents, half-up rounding through `percent_of`, no floats or
  `round()`, no new dependencies;
- says which behavior must not change (expiry, unknown codes, case-insensitivity, `promo_percent`'s return
  value, the order of operations);
- asks for the module docstring's business rules to be updated;
- defines done: the exact test command to run, and that it should show you the output rather than just say
  the tests pass.

## Example prompt

<details>
<summary>Show the example prompt</summary>

```text
In labs/electives/e2-agent-ready-repo/work.py, add a per-code cap on promo discounts.

1. Add a "max_off_cents" key to every entry in PROMO_CODES: an int number of cents, or None for no cap.
   WELCOME10 gets 2500. SPRING5 and VIP20 get None.
2. Add a small function promo_discount_cents(code, subtotal_cents, today) that returns
   percent_of(subtotal_cents, promo_percent(code, today)), capped at the code's max_off_cents when that
   isn't None. Use it in order_total_cents in place of the current promo line. Tax must still apply to the
   subtotal after the capped discount.
3. Read the cap from PROMO_CODES. Don't special-case "WELCOME10" anywhere in code.
4. Update the business-rules list in the module docstring with the cap rule.

Constraints: all money stays integer cents; use percent_of for any percentage; no floats, no round(), no new
imports or dependencies. Keep promo_percent's behavior and return value exactly as they are (case-insensitive,
trimmed, rejects unknown and expired codes). Don't change bulk tiers, rounding, tax, or the input checks.

Only edit work.py. Don't edit test_pricing.py, test_lab_setup.py, solution.py, starter.py, or anything under
setups/ or holdout/.

When you're done, run these from the labs folder and show me the last lines of each:
  pytest electives/e2-agent-ready-repo -q
  pytest electives/e2-agent-ready-repo/test_change.py -q
```

</details>

## Review the AI's change

Read the diff (`diff solution.py work.py`) before you run anything, and check:

- [ ] **Scope.** Only `work.py` changed. No test file, no `setups/` or `holdout/` file, no new file such as
      a `conftest.py`.
- [ ] **Data, not special cases.** Every `PROMO_CODES` entry has `max_off_cents`, and the code reads it.
      There's no `if code == "WELCOME10"` (or an uppercase comparison that amounts to the same thing).
- [ ] **Integer money.** The cap uses `min(...)` on integers. No `/`, `round()`, or float anywhere in the new
      code; the percentage still goes through `percent_of`.
- [ ] **Order of operations.** Bulk discount, then the capped promo, then tax on what's left. The cap isn't
      applied per line, and tax isn't computed before the cap.
- [ ] **Safeguards kept.** Unknown and expired codes still raise `PricingError`, and the expiry check still
      runs for a capped code. `promo_percent` still returns the plain percent (a version that changed it to
      return cents, or a tuple, breaks every caller that expects an int).
- [ ] **No silent fallback.** A missing `max_off_cents` key shouldn't be quietly treated as "no cap" with
      `.get()` when the spec says every entry declares it. If the assistant chose `.get("max_off_cents")`,
      ask why, and decide whether you want that leniency.
- [ ] **Docs.** The module docstring's rules mention the cap, and any new function has a docstring that says
      what it returns.
- [ ] **Evidence.** The assistant showed you the test output, not just "all tests pass".

## Check it

From the `labs` folder:

```bash
pytest electives/e2-agent-ready-repo/test_change.py -q
```

All 12 should pass. Several of them (an exactly-at-the-cap order, an uncapped code, an expired capped code)
pass before the change as well; they're there to prove the change didn't break existing behavior. One test
temporarily gives VIP20 a cap to make sure the cap is read from the data.

Then run the full lab to make sure nothing else broke:

```bash
pytest electives/e2-agent-ready-repo -q
```

Expect `28 passed, 12 skipped`: with `work.py` in place, `test_pricing.py` runs against your changed code,
and the 12 change tests are skipped in a full run (they only run when you name `test_change.py`). Compare with `change_solution.py` if you want to see one clean way to do
it, but only after you've reviewed the assistant's version on its own merits.
