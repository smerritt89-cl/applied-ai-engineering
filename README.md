# Applied AI Engineering

A personal, self-paced program in applied AI engineering. It's modeled on a professional master's but graded on what you build.
Six studios plus a capstone (about 7 to 8 months at 8 to 10 hours a week) take you from a first API call to a production system with
retrieval, agents, and evaluations. Every studio ends in a portfolio project built in its own repo.

The platform is a static site: no backend and no accounts. Your progress lives in your browser's localStorage, and you can back it
up from Settings.

| Studio | Topic | Project |
|---|---|---|
| 1 | LLM App Fundamentals: APIs, prompting, structured outputs, tool calling | Meeting transcript to action items |
| 2 | Retrieval & RAG: embeddings, chunking, vector DBs, hybrid search, reranking | Q&A over a real document set |
| 3 | Evaluation: test sets, LLM-as-judge, regression testing | Eval harness that measurably improves Studio 2 |
| 4 | Agents & MCP: multi-step agents, tool use, MCP servers, guardrails | Agent that automates a PM workflow |
| 5 | Open Models & Fine-Tuning: Hugging Face, LoRA, fine-tune vs. prompt | Fine-tuned extractor benchmarked against a frontier model |
| 6 | Shipping to Production: deployment, cost, latency, observability, guardrails | Best earlier project, live, with logging and a cost dashboard |
| Capstone | RAG + agents + evals in one system | Public write-up, eval results, recorded demo |
| Electives | Let's Build GPT · Working with Coding Agents · Frontier Perspectives | |

## Quick start

Requires Node 22+ (see `.nvmrc`).

```bash
npm install
npm run dev          # http://localhost:4321/applied-ai-engineering/
```

Other commands:

| Command | What it does |
|---|---|
| `npm run build` | Regenerates `CREDITS.md`, then builds the static site into `dist/` |
| `npm run preview` | Serves the built site locally |
| `npm test` | Unit tests for grading and progress logic (Vitest) |
| `npm run audio:setup` | One-time: creates the Python environment for narration |
| `npm run audio` | Builds, generates any missing narration, and builds again |
| `npm run check:videos` | Confirms every embedded YouTube id exists (oEmbed) |
| `npm run check:links` | Checks every source URL in `src/content/sources/` |
| `npm run verify` | All checks, tests, and a build: run it before you push |

## How it's built

**Stack: Astro 7 + MDX + Preact islands + TypeScript.** Astro is built for content-heavy static sites. Lessons are Markdown/MDX,
validated against Zod schemas at build time, and pages ship no JavaScript except the interactive pieces (quiz engine,
Python runner, dashboard). Those are small Preact "islands" (Preact is about 3 KB with React's API). It deploys to GitHub Pages with
the official actions.

```
src/
  content.config.ts      Schemas for every content type: the contract between content and UI
  content/
    studios/*.yaml       Studio metadata: outcomes, weeks, project and exam ids
    lessons/<studio>/*.mdx
    quizzes/*.json       One graded quiz per week
    exams/*.json         Question pool per studio (20 drawn per attempt)
    projects/*.mdx       Project brief (body) + checklist and rubric (frontmatter)
    sources/*.yaml       Every source with its license; generates CREDITS.md
  components/
    lesson/              Listen, Video, Callout, GoDeeper, Mermaid, Predict, LabLink (Astro)
                         PyRunner, DragOrder (Preact islands)
    assess/              QuestionCard, KnowledgeCheck, TestRunner (quizzes + exams), ProjectTracker
    dashboard/           Dashboard, StudioProgress, Transcript, HoursLog, SettingsPanel
  lib/
    progress.ts          localStorage store: versioned, migrations, subscribe, export/import
    grading.ts           All grading rules (pure functions, unit-tested)
    questions.ts         Build-time Markdown + Shiki highlighting for questions
    narration.ts         Narration text extraction and hashing (shared with the TTS script)
    pyodide-worker.ts    Python in a Web Worker; python.ts is its client
    timer.ts             Active-time tracking on lesson pages
    program.ts           Ordered view of studios, lessons, quizzes, exams, projects
  pages/                 Routes: dashboard, studios, lessons, quizzes, exams, projects, transcript, hours, settings, credits
labs/                    Local Python exercises that need API keys (pytest, offline + live tests)
scripts/                 TTS pipeline, credits generator, link and video checkers
public/audio/            Generated narration (MP3 + WebVTT captions + manifest)
public/project-data/     Sample data for studio projects
```

### Progress and grading

All progress is one JSON document in localStorage under `aae:v1` (`src/lib/progress.ts`). It records completed lessons, active
time per lesson, knowledge-check first tries, exercise passes, every quiz and exam attempt, project checklists, rubric scores and
links, manual hours, lesson notes, and settings. Settings has **Export** and **Import** buttons: back up now and then, because browsers can clear storage.

Grading lives in `src/lib/grading.ts` and is documented on the Syllabus page: quizzes 30%, exam 30% (80% to pass), project rubric
40%. Grades are provisional until a studio is complete. Answers ship with the page (it's a static site), so quizzes run on the honor system.

### Notes

Every lesson page has a **My notes** column on the right (a ✎ Notes button on narrower screens) that stays in view as you scroll.
Notes save as you type. **⏱ Insert time** stamps the position of the video or narration you are playing, for example
`[video 3:09]`, by reading the YouTube embed's time through its postMessage channel (`enablejsapi=1`). The **Notes** page
collects every note in course order, with search, copy, and a Markdown download (`src/components/lesson/NotesPanel.astro`,
`src/pages/notes.astro`).

### Narration (Listen buttons)

Each `<Listen>` section in a lesson gets a player. If generated audio exists for that exact text, it plays an MP3 with synchronized
captions; otherwise it falls back to the browser's built-in voice (Web Speech API).

Generating audio uses [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), an open-weight TTS model (Apache 2.0), through
`kokoro-onnx`. It runs locally on CPU at several times real time, and needs `ffmpeg` (`brew install ffmpeg`).

```bash
npm run audio:setup   # once: Python venv + kokoro-onnx (model files, ~340 MB, download on first run)
npm run audio         # build, synthesize what's missing, build again
python3 scripts/tts/generate.py --prune   # remove audio for text that no longer exists
python3 scripts/tts/generate.py --voice am_michael   # pick another Kokoro voice
```

Sections are keyed by a hash of their text, so editing a paragraph regenerates only that section. Pronunciation fixes for
acronyms (JSON, LLM, API, ...) are in `SPEAK_AS` in `scripts/tts/generate.py`. Commit the generated `public/audio/` files: CI
doesn't run TTS.

### Videos

`<Video>` embeds official YouTube videos through the privacy-enhanced player, behind a click-to-load facade. Captions are on by
default, and there is always a link to the source. Videos are never downloaded or rehosted. `npm run check:videos` verifies every id.

### In-browser Python

`<PyRunner>` runs Python with [Pyodide](https://pyodide.org) in a Web Worker (loaded from jsDelivr on first use, about 10 MB). Exercises have hidden
`assert` tests; passing is recorded in your progress. Runaway loops are stopped by a timeout. Anything that needs an API key, network
access, or a GPU is a local lab in `labs/` instead (see `labs/README.md`).

## Adding content

Read **[CONTENT_GUIDE.md](CONTENT_GUIDE.md)** first. It covers sourcing rules, licenses, every component, MDX gotchas, the question
schema, and lab conventions. In short:

1. **Lesson:** create `src/content/lessons/<studio>/w<week>-l<n>-<slug>.mdx` with the frontmatter shown in the guide. It appears
   in the studio automatically, ordered by week and `order`. Cite every source by id from `src/content/sources/*.yaml`.
2. **Quiz:** add `src/content/quizzes/<studio>-w<week>.json`. It's linked from the week automatically.
3. **Exam:** add questions to `src/content/exams/<studio>-exam.json` (keep at least 30, tagged by `week`).
4. **Project:** `src/content/projects/<studio>-project.mdx`; the frontmatter holds the checklist and rubric, the body is the brief.
5. **New studio:** add `src/content/studios/<id>.yaml` and set `status: available` when it has lessons.
6. Run `npm run verify`, then `npm run audio` to narrate new sections.

The build fails with a clear message if frontmatter doesn't match the schema, or a lesson cites a source that doesn't exist.
**Never rename a lesson, quiz, or exam id after you start using it**: ids are the keys of your saved progress.

## Deploying to GitHub Pages

1. Create a GitHub repo (for example `applied-ai-engineering`) and push this folder to `main`.
2. In the repo: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. Edit `src/site.config.ts`: set `REPO_URL` and `GITHUB_USER` (used for lab links and project repo suggestions).
4. Push. `.github/workflows/deploy.yml` runs the tests, builds with the right base path from the Pages configuration, and deploys.
   The site appears at `https://<user>.github.io/<repo>/`.

To build for another host or a custom domain locally: `SITE_URL=https://example.com BASE_PATH= npm run build`.

Your progress is stored per site origin, so progress on `localhost` and on GitHub Pages is separate. Use Export/Import to move it.

## Licensing

- Platform code: MIT (`LICENSE`).
- Course content: CC BY-NC-SA 4.0 (`LICENSE-CONTENT`), because adapted MIT OpenCourseWare material requires ShareAlike and adapted
  Anthropic course material requires NonCommercial. Keep the site non-commercial.
- Every source, its license, and where it's used: `CREDITS.md` (generated) and the Credits page.
