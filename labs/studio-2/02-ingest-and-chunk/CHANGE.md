# Change: ignore headings inside fenced code blocks

## The change

`split_sections` finds headings with a regular expression that matches any line starting with `#`. Inside a fenced code block, that is wrong: a shell comment such as `# install deps` or a Python comment is code, not a heading. Today such a line starts a new "section" with a nonsense heading path, cuts the code block in half, and separates the commands from the explanation above them. Runbooks and engineering docs are full of code blocks, so this bug would hit a real corpus quickly.

Change `split_sections` so that lines inside fenced code blocks are never treated as headings:

- A fence is a line that starts with three backticks or three tildes (up to three leading spaces are allowed, as in standard Markdown).
- A block opened with backticks closes only at a backtick fence, and one opened with tildes closes only at a tilde fence.
- A fence that is never closed runs to the end of the text.
- Everything else about `split_sections` stays the same: heading paths, skipping headings with no body, the preamble section, and the offsets.

`chunk_markdown` uses `split_sections`, so it picks up the fix automatically. The work happens in `work.py` (your copy of `solution.py`).

## Write your prompt

Write your own prompt for a coding assistant first, then compare it with the example below. A good prompt for this change:

- Names the function and describes the bug with a concrete example (a `# comment` line inside a code block).
- Defines a fence precisely, including the matching-marker rule and the unclosed-fence rule. Without that, an assistant may only handle backticks, or treat every fence line as a toggle.
- Says what must not change: heading paths, the empty-heading skip, the preamble, and the `start`/`end` offsets that must still slice the source exactly.
- Keeps scope tight: no changes to `_pack`, the chunk size logic, or other stages.
- Asks for tests: a comment inside a fence, mismatched fence markers, an unclosed fence, and a document with no fences behaving as before.

## Example prompt

<details>
<summary>Show the example prompt</summary>

```text
In work.py, split_sections treats any line matching HEADING_RE as a heading, including
lines inside fenced code blocks such as "# install deps" in a bash block. Fix it so
headings inside fenced code blocks are ignored.

Definition of a fence: a line starting with ``` or ~~~, with at most three leading
spaces. A block opened with ``` closes only at a ``` line, and one opened with ~~~
closes only at a ~~~ line. An unclosed fence runs to the end of the text.

Implement this with a small helper that returns the (start, end) character offsets of
fenced blocks, and filter out heading matches whose start falls inside one. Keep
everything else about split_sections the same: the heading-path logic, skipping
headings with no body, the preamble section, and the start/end offsets. Do not change
_pack, chunk_markdown, chunk_fixed, or any other function.

Add tests for: a "#" comment inside a backtick fence (the code stays in its section),
a ``` line inside a ~~~ fence not closing it, an unclosed fence, chunk_markdown keeping
the code block with its heading, and a document with no fences giving the same
sections as before. Run the existing tests too.
```
</details>

## Review the AI's change

- [ ] **Scope.** Only `split_sections` changed, plus at most a new helper and a compiled regex. `_pack`, `chunk_fixed`, `make_chunks`, and the store are untouched.
- [ ] **Fence rules.** Both backticks and tildes are handled, markers must match to close, and an unclosed fence runs to the end. Check that it doesn't simply flip an "inside code" flag on every fence line, which breaks the mismatched-marker case.
- [ ] **Offsets still exact.** Sections still use character offsets into the original text, and chunks still satisfy `text[start:end] == chunk text`. The fix should filter heading matches, not edit or strip the text.
- [ ] **Old behavior intact.** Documents without fences produce exactly the same sections. The full lab suite still passes.
- [ ] **Edge cases tested.** There are tests for a comment in a fence, mismatched markers, an unclosed fence, and no fences.
- [ ] **No new dependency.** The fix uses `re` from the standard library, not a Markdown parsing package, unless you asked for one.

One thing this change does not fix: a code block longer than `max_chars` can still be split in the middle by `_pack`. That is a separate decision (keep big code blocks whole and accept larger chunks, or split them), and it is fine for the assistant to leave it alone. If it changed `_pack` anyway, that is scope creep.

## Check it

From the `labs` folder:

```bash
pytest studio-2/02-ingest-and-chunk/test_change.py -q
pytest studio-2/02-ingest-and-chunk -q
```

The first command runs the acceptance tests for this change; they fail until the change is made. The second runs the lab's full suite to make sure nothing else broke.
