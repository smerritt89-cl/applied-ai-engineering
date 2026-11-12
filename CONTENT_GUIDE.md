# Content authoring guide

How to write lessons, quizzes, exams, projects, and labs for this platform.
The reference implementation is `src/content/lessons/s1/w1-l1-how-llms-work.mdx`:
read it before writing anything, and match its structure, tone, and density.

## 1. Sourcing rules (non-negotiable)

The learner asked for **credibly sourced content only**. Every factual claim must
trace to a source listed in the lesson's `sources` frontmatter.

- **Acceptable sources:** official documentation (Anthropic, OpenAI, Google,
  xAI, Hugging Face, framework docs), peer-reviewed papers or arXiv preprints from
  recognized labs, the licensed open courses below, primary statements by the
  people involved (talks, essays, interviews on official channels), and
  established practitioners' writing (Chip Huyen, Hamel Husain, Eugene Yan, Simon
  Willison) for practice and opinion, clearly framed as such.
- **Not acceptable:** content farms, SEO listicles, unsourced Medium posts,
  vendor marketing presented as fact, social-media hearsay, or your memory alone.
- **Verify every URL** you add with `curl -sIL -o /dev/null -w '%{http_code}' URL`
  (expect 200; some sites return 403 to curl, so confirm those with a fetch).
  Verify every YouTube ID with
  `curl -s "https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=ID&format=json"`.
- **Fast-moving facts** (model names, prices, context windows, benchmark scores,
  API parameters) must come from a source you checked today, and the lesson's
  `reviewed:` date must be today. Prefer wording that ages well ("at the time of
  writing", "check the pricing page") over precise numbers that will rot, unless
  the numbers are the point of the exercise.
- **Opinions and predictions** by industry figures go in `<Callout type="claim">`
  with the speaker, the date, a link, and the evidence for and against.

### Licenses: what you may do with each source

| Policy in sources.yaml | Examples | What you may do |
|---|---|---|
| `adapt` | Microsoft GenAI/Agents for Beginners (MIT), Hugging Face courses (Apache 2.0), mlabonne/llm-course (Apache 2.0), Anthropic courses (CC BY-NC 4.0), MIT OCW (CC BY-NC-SA) | Adapt structure, explanations, and exercises with attribution (`use: adapted`). Still rewrite in this course's voice. |
| `summarize` | Docs, books, blogs, papers | Summarize ideas **in your own words** and link. No copied passages. At most one direct quote per lesson, under 15 words, in quotation marks, attributed. |
| `embed` | YouTube videos | Embed with `<Video>` (official player). Never download, transcribe in full, or rehost. |

Never paste copyrighted text, code, or figures. Short code examples that use an
SDK the way its docs show are fine: they are written fresh, not copied.

### Claude API accuracy

API shapes changed a lot in 2025 and 2026. Before writing any Claude API code
or describing parameters, load the `claude-api` skill and follow it (current
model ids, `output_config`, adaptive thinking and effort, no sampling params on
the current API version, no assistant prefill, structured outputs, tool use).
Default model in examples: `claude-opus-5-5`; use `claude-haiku-5-5` or
`claude-sonnet-5-5` in examples about cost or routing. For other providers,
check their docs before writing code, and keep non-Claude code short.

## 2. Files and ids

| Content | Location | Id rule |
|---|---|---|
| Lesson | `src/content/lessons/<studio>/w<week>-l<n>-<slug>.mdx` | `id: <studio>-w<week>-l<n>` (e.g. `s2-w3-l7`); `order` = n within the week order; n counts across the studio |
| Quiz | `src/content/quizzes/<studio>-w<week>.json` | `id: <studio>-w<week>` |
| Exam | `src/content/exams/<studio>-exam.json` | `id: <studio>-exam` |
| Project | `src/content/projects/<studio>-project.mdx` | `id: <studio>-project` |
| Sources | `src/content/sources/<studio>.yaml` | unique across all source files; check `core.yaml` first |
| Lab | `labs/studio-<n>/<nn>-<slug>/` | README.md, starter.py, solution.py, test_*.py |

Ids are saved in learners' progress. **Never rename an id once published.**

## 3. Lesson anatomy

Frontmatter fields are defined (and validated) in `src/content.config.ts`.
Required: `id, studio, week, order, title, summary, estMinutes, objectives,
sources (min 1), knowledgeCheck (2 to 4 questions), reviewed`.

**Rhythm.** Every lesson mixes all four:
1. **Short reads** inside `<Listen>` blocks (each 150 to 400 words, one idea per block).
2. **A video or audio segment**: a `<Video>` from an official channel, or the narration itself when no good video exists. Never invent a video.
3. **A hands-on exercise**: `<PyRunner>` (stdlib or Pyodide packages only, with `tests` and `solution`), `<Predict>`, `<DragOrder>`, or a `<LabLink>` for anything needing an API key.
4. **A knowledge check** (frontmatter `knowledgeCheck`, rendered automatically).

Plus at least one `<Callout type="pitfall">`, and `<GoDeeper>` for optional depth.
Target 40 to 70 minutes per lesson including the exercise.

### Components

Available in every lesson without importing: `Listen, Video, Callout, GoDeeper,
Mermaid, Predict, LabLink`. Islands must be imported at the top of the MDX:

```mdx
import PyRunner from '@components/lesson/PyRunner';
import DragOrder from '@components/lesson/DragOrder';
```

```mdx
<Listen>
## Heading inside the block
Prose. Keep code and interactive components OUTSIDE Listen blocks.
</Listen>

<Video id="YOUTUBE_ID" title="Exact title" channel="Channel name" minutes={12} start={0} source="https://official-page">
What to watch for (optional).
</Video>

<Callout type="pitfall|tip|note|claim" title="Optional title">Markdown body.</Callout>

<GoDeeper title="Topic">Optional depth.</GoDeeper>

<Mermaid alt="Full text description for screen readers" caption="Optional" chart={`flowchart LR
  A["Label"] --> B["Label"]`} />

<Predict title="..." code={`print(1 + 1)`} options={["2", "11", "Error"]} answer={0}>
Explanation.
</Predict>

<PyRunner client:visible id="unique-exercise-id" title="..." starter={`...`} tests={`assert f(1) == 2, "message"`} solution={`...`} packages={["pydantic"]}>
Instructions.
</PyRunner>

<DragOrder client:visible prompt="..." items={["first", "second", "third"]} explanation="..." />

<LabLink path="labs/studio-1/01-first-call" title="..." needs={["Anthropic API key"]} minutes={30}>
One-paragraph description.
</LabLink>
```

### MDX gotchas

- Curly braces in prose start a JavaScript expression. Write them inside code spans (`` `{"a": 1}` ``) or avoid them.
- A bare `<` followed by a letter in prose starts a tag. Write "less than" or use a code span.
- Inside template-literal props (`` code={`...`} ``), escape backticks and `${`.
- In YAML frontmatter, quote strings containing `: `, `#`, or leading special characters. Use `>-` for long text.

## 4. Questions (knowledge checks, quizzes, exams)

One schema for all three (see `questionSchema`):

```json
{
  "id": "s1w2-q3",
  "type": "mcq | multi | code-reading | predict-output | scenario",
  "prompt": "Inline markdown: `code`, **bold**",
  "code": "optional code block (code-reading, predict-output)",
  "language": "python",
  "options": [
    { "id": "a", "text": "...", "correct": true, "rationale": "Why this is right" },
    { "id": "b", "text": "...", "rationale": "Why this is wrong" }
  ],
  "explanation": "Shown after answering. Teach, don't just restate.",
  "week": 2,
  "tags": ["prompting"],
  "difficulty": 2
}
```

- Exactly one correct option, except `multi` (one or more).
- Every option gets a `rationale`. Vary the position of the correct answer.
- Distractors must be plausible mistakes a learner would actually make.
- `scenario` = "what would you do" situations from real engineering work, with a best choice and reasons.
- **Quizzes:** 10 questions per week, all five types represented, at least 2 scenarios and 2 code-reading or predict-output.
- **Exam pool:** at least 30 questions per studio (exam draws 20), balanced across weeks via the `week` field, at least a third applied scenarios. Don't reuse quiz questions verbatim.

## 5. Labs

Each lab folder contains:
- `README.md`: goal, steps, expected cost of live tests, and what to notice.
- `starter.py`: functions with `TODO`s and docstrings.
- `solution.py`: a working reference.
- `test_<name>.py`: offline tests (pure logic, a fake client, or recorded responses) plus optional `@pytest.mark.live` tests that call the API.

Tests import from `starter` (the learner's file). Make offline tests meaningful,
so a learner without an API key still learns. Use the official `anthropic` SDK.

## 6. Voice and style

- Second person, plain and direct, for a mathematically literate professional who is new to ML engineering. Explain jargon on first use.
- Short paragraphs. Concrete examples from real work (product, PM, operations), not toy trivia.
- **Checks and balances** is a running theme: whenever a technique produces model output, say how to verify it.
- **Model selection** is a running theme: when it matters, say which kinds of models suit the task and how you'd decide with evidence.
- No em dashes or en dashes; use commas, colons, parentheses, or separate sentences.
- No hype. Distinguish what is demonstrated from what is claimed.
