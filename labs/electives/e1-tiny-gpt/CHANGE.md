# Change: add top-k filtering to `stable_softmax`

## The change

Temperature alone has a weakness when you sample from a character model: even at a sensible temperature, the long tail of unlikely characters together keeps a noticeable share of the probability, so every so often a sample picks something absurd and the text derails. **Top-k sampling** fixes that by keeping only the k most likely tokens, setting every other probability to exactly zero, and renormalizing the rest. It's a standard option in GPT sampling code, and you'll want it when you write `generate` for the project.

Add an optional `top_k` argument to `stable_softmax` in `work.py`:

- `top_k=None` (the default) means no filtering: the function behaves exactly as it does now.
- With `top_k=k`, every logit strictly below the k-th largest (after dividing by the temperature) gets probability 0, and the kept entries are renormalized. Logits **tied** with the k-th largest are all kept, so more than k entries can be nonzero when there are ties.
- `top_k` at or above the number of logits changes nothing.
- `top_k` below 1 raises `ValueError`.
- The function must stay numerically stable for large logits.

Mathematically, this is the softmax restricted to the set S of kept indices: p_i = exp(z_i / T) / sum over j in S of exp(z_j / T) for i in S, and 0 otherwise. The relative odds between kept tokens don't change.

## Write your prompt

Write your own prompt for a coding assistant (Claude Code, for example) before you look at the example. The work happens in `work.py`, your copy of the solution. A good prompt for this change:

- names the function and the exact new parameter, with its default and type;
- defines the rule precisely, including the two cases an assistant is likely to improvise on: **ties** at the k-th value, and `top_k` larger than the number of logits;
- says what must not change (the default behavior, the temperature check, the subtract-the-max step, other functions);
- says how invalid values should fail;
- asks for the docstring to be updated and for tests, and names the cases they must cover.

## Example prompt

<details>
<summary>Show the example prompt</summary>

> In `labs/electives/e1-tiny-gpt/work.py`, add an optional keyword argument `top_k: int | None = None` to `stable_softmax`.
>
> Behavior: after dividing the logits by the temperature, if `top_k` is set and is smaller than the number of logits, find the k-th largest scaled value and treat every value strictly below it as minus infinity, so its probability is exactly 0.0. Keep all values tied with the k-th largest. Then do the existing stable softmax (subtract the max, exponentiate, normalize). If `top_k` is at least the number of logits, change nothing. If `top_k` is less than 1, raise `ValueError`.
>
> Don't change anything else: `top_k=None` must give exactly the same output as now, keep the existing temperature check and the subtract-the-max step, and don't touch any other function. No new imports beyond the standard library.
>
> Update the docstring to describe `top_k`, including the tie rule. Then show me the diff before making other changes.

</details>

## Review the AI's change

Before you run anything, read the diff and check:

- **Scope.** Only `stable_softmax` changed. No other function, no new dependency (numpy is a common unrequested addition), no reformatting of unrelated lines.
- **Default behavior.** With `top_k=None`, the code path is the same as before. A version that always sorts or always filters is a behavior change even if the numbers happen to agree.
- **Where the filter happens.** Filtering is applied to the **scaled** logits, before the softmax, by pushing dropped entries to minus infinity (or an equivalent). Zeroing probabilities **after** the softmax without renormalizing leaves a distribution that doesn't sum to 1.
- **Ties and boundaries.** Look for the comparison against the threshold: `>=` keeps ties, `>` would drop the k-th value itself. Check what happens when `top_k` equals or exceeds the number of logits, and that `top_k=0` or negative raises `ValueError` instead of returning all zeros or crashing on an index.
- **Stability.** The subtract-the-max step is still there. Since the maximum is always kept, `max` of the filtered list is finite.
- **Docs and hints.** The docstring describes the new parameter and the tie rule, and the type hint says `int | None`.

## Check it

From the `labs` folder, run the acceptance tests for this change:

```bash
pytest electives/e1-tiny-gpt/test_change.py -q
```

They fail before the change and pass once it's right. Then run the full lab to make sure nothing else broke:

```bash
pytest electives/e1-tiny-gpt -q
```

If you want to compare against a reference, `change_solution.py` has the change applied. Read it only after you've reviewed the assistant's version.
