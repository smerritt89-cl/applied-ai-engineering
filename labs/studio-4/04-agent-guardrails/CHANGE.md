# Change: let private data reach internal colleagues, with approval

## The change

Rule 5 of `Guard.check` denies any outbound call that contains private data, including an email to a colleague at
`acme.example`. The lab README calls this a deliberate over-block. Your account lead now wants the agent to be able
to email the renewal context to the PM, which today is impossible: the guard denies it before any person can say
yes.

Relax rule 5 for one case only: a `send_email` call whose **every** destination is an internal email domain should
be **asked** (a person approves it, seeing the exact text) instead of denied. Everything else stays as it is:

- Add a module constant `INTERNAL_EMAIL_DOMAINS = {"acme.example"}` and a matching `Guard` field
  `internal_email_domains`, so each guard can be configured.
- "Every destination" means every host `destinations()` finds in the arguments: all recipient domains and any URL
  hosts inside the subject or body. One outsider, or one link to another host, keeps the deny.
- Domains match exactly. `docs.acme.example` is a separate system with its own logs, so it does not qualify, and
  lookalikes such as `acme.example.evil.example` are already denied by rule 3.
- The ask's reason should say why: `"private data to internal recipients requires approval"`.
- `fetch_url` and `post_status` are not relaxed, and the scorer (`attack_succeeded`) does not change. The scorer
  measures the guard; loosening the guard must not loosen the measurement.

This is a real design pattern: when a rule over-blocks, turn the narrow legitimate case into an ask, and write the
abuse tests for the relaxation at the same time. The work happens in `work.py`.

## Write your prompt

Write your own prompt for a coding assistant before you open the example. A good prompt for a security change says:

- exactly which rule changes and the one case that gets relaxed, in terms of the existing functions
  (`destinations`, `Guard.check`, rule 5);
- what the new decision and reason are;
- what must **not** change: the other rules, their order (every deny before every ask), other egress tools, the
  scorer, and the existing tests;
- the abuse cases you expect to stay denied (mixed recipients, a subdomain, a lookalike, a link in the body);
- which tests to add.

## Example prompt

<details><summary>Show an example prompt</summary>

```text
In work.py (Studio 4 lab 04), relax rule 5 of Guard.check for internal email only.

Today rule 5 denies any egress tool whose args contain a private value. Change it so that a
send_email call is answered Decision("ask", "private data to internal recipients requires approval")
when EVERY host returned by destinations(name, args) is exactly in the guard's internal email domains.
Otherwise rule 5 still denies with the existing reason.

- Add INTERNAL_EMAIL_DOMAINS = {"acme.example"} next to INTERNAL_CHANNELS, and a Guard field
  internal_email_domains with default_factory copying it (same pattern as allowed_hosts).
- Put the "every destination is internal" test in a small helper method with a docstring.
  Exact match only: no subdomains. A call with no destinations does not qualify.
- Update the check() docstring's rule list.

Do not change: rules 1 to 4 and 6 to 8, the order of the rules, fetch_url or post_status handling,
attack_succeeded, run_agent, or any existing test. Do not add the attacker hosts to the guard.

Add tests (pytest, offline) for: internal recipient with private data -> ask with that reason;
"pm@acme.example, audit@partner-audit.example" -> deny; pm@docs.acme.example -> deny;
pm@acme.example.evil.example -> deny; an internal email whose body links to docs.acme.example with
private data in the query -> deny; fetch_url with private data to acme.example -> still deny.
```

</details>

## Review the AI's change

- [ ] **Scope:** only rule 5 changed. The other seven rules, and their order, are untouched. In particular, every
  deny still comes before every ask, so a rubber-stamp reviewer still cannot approve any fixture attack.
- [ ] **All destinations, not just `to`:** the relaxation looks at every host `destinations()` finds, so a link in
  the body or a second recipient keeps the deny. A version that parses only the `to` field is a new leak path.
- [ ] **Exact domain match:** it compares with `in self.internal_email_domains`, not `host_allowed` (which would
  admit subdomains) and not a substring or `endswith` check.
- [ ] **Empty case:** a call with no destinations does not count as "internal only" (`all()` of an empty list is
  `True`, so look for an explicit non-empty check).
- [ ] **No collateral changes:** `fetch_url`, `post_status`, `attack_succeeded`, and `run_agent` are unchanged, and
  the guard still does not read `ATTACKER_HOSTS`.
- [ ] **Docs and tests:** the `check` docstring lists the exception, the new Guard field has a default factory, and
  tests cover both the relaxed case and the abuse cases.

## Check it

From the `labs` folder:

```bash
pytest studio-4/04-agent-guardrails/test_change.py -q
pytest studio-4/04-agent-guardrails -q
```

The first command runs the acceptance tests for this change; they fail until the change is in `work.py`. The second
runs the full lab suite to make sure nothing else broke: attack success must still be 0% with the guard on, and
utility 100%.
