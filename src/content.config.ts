/**
 * Content schemas: the contract between Markdown/JSON content and the UI.
 *
 * Every file under src/content/ is validated against these Zod schemas at
 * build time. A typo in frontmatter (e.g. `pasingScore`) or a malformed quiz
 * question fails `npm run build` with a pointer to the file, instead of
 * silently breaking a page. When you add a new field, add it here first.
 */
import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

/* ------------------------------------------------------------------ */
/* Shared pieces                                                       */
/* ------------------------------------------------------------------ */

/** Studio keys: s1..s6 for the core studios, plus capstone and electives. */
export const studioKey = z.string().regex(/^(s[1-6]|capstone|e[1-9])$/);

/**
 * One assessment question. The same shape is used by lesson knowledge
 * checks, weekly quizzes, and studio exams, so the renderer and grader
 * only need to understand one format.
 *
 * - mcq / code-reading / predict-output / scenario: exactly one correct option
 * - multi: one or more correct options ("select all that apply")
 */
export const questionSchema = z
  .object({
    id: z.string(),
    type: z.enum(['mcq', 'multi', 'code-reading', 'predict-output', 'scenario']),
    /** Inline Markdown: `code`, **bold**, *italic*, [links](url). */
    prompt: z.string(),
    /** Optional code shown under the prompt (code-reading, predict-output). */
    code: z.string().optional(),
    language: z.string().default('python'),
    options: z
      .array(
        z.object({
          id: z.string(),
          text: z.string(),
          correct: z.boolean().default(false),
          /** Why this option is right or wrong. Shown after answering. */
          rationale: z.string().optional(),
        }),
      )
      .min(2),
    /** Shown after answering, regardless of correctness. */
    explanation: z.string(),
    /** Week of the studio this question covers (used to balance exam draws). */
    week: z.number().int().min(1).max(8).optional(),
    tags: z.array(z.string()).default([]),
    difficulty: z.number().int().min(1).max(3).default(2),
  })
  .refine((q) => q.options.some((o) => o.correct), {
    message: 'Every question needs at least one correct option',
  })
  .refine((q) => q.type === 'multi' || q.options.filter((o) => o.correct).length === 1, {
    message: 'Only "multi" questions may have more than one correct option',
  });

export type Question = z.infer<typeof questionSchema>;

/** A citation from a lesson to an entry in sources.yaml. */
const sourceRef = z.object({
  id: z.string(),
  /** adapted = derived text/structure (license permits); summarized = our own words; linked = further reading. */
  use: z.enum(['adapted', 'summarized', 'linked', 'embedded']),
  /** Which part of the source (chapter, lesson, section, timestamp). */
  where: z.string().optional(),
});

/* ------------------------------------------------------------------ */
/* Collections                                                         */
/* ------------------------------------------------------------------ */

/** Studio metadata: one YAML file per studio, capstone, or elective. */
const studios = defineCollection({
  loader: glob({ pattern: '*.yaml', base: './src/content/studios', generateId: ({ data }) => String(data.id) }),
  schema: z.object({
    id: studioKey,
    number: z.number().int(), // display order
    kind: z.enum(['studio', 'capstone', 'elective']).default('studio'),
    title: z.string(),
    tagline: z.string(),
    summary: z.string(),
    status: z.enum(['available', 'coming-soon']).default('coming-soon'),
    estWeeks: z.number(),
    estHours: z.number(),
    outcomes: z.array(z.string()),
    weeks: z
      .array(z.object({ week: z.number().int(), title: z.string(), summary: z.string() }))
      .default([]),
    project: z.string().optional(), // id in the projects collection
    exam: z.string().optional(), // id in the exams collection
    /** Accent color for cards and progress bars (CSS color). */
    accent: z.string().default('var(--accent)'),
  }),
});

/** Lessons: MDX files grouped in a folder per studio. */
const lessons = defineCollection({
  loader: glob({ pattern: '**/*.mdx', base: './src/content/lessons', generateId: ({ data }) => String(data.id) }),
  schema: z.object({
    id: z.string().regex(/^[a-z0-9-]+$/), // stable key used in URLs and saved progress; never rename
    studio: studioKey,
    week: z.number().int().min(1),
    order: z.number().int().min(1),
    title: z.string(),
    summary: z.string(),
    estMinutes: z.number().int(),
    objectives: z.array(z.string()).min(1),
    sources: z.array(sourceRef).min(1),
    /** 2 to 4 ungraded questions rendered at the end of the lesson. */
    knowledgeCheck: z.array(questionSchema).min(2).max(4),
    /** Last date the facts in this lesson were checked against sources (YYYY-MM-DD). */
    // YAML turns an unquoted 2026-11-11 into a Date; accept either and normalize to a string.
    reviewed: z
      .union([z.string().regex(/^\d{4}-\d{2}-\d{2}$/), z.date()])
      .transform((d) => (typeof d === 'string' ? d : d.toISOString().slice(0, 10))),
  }),
});

/** Weekly graded quizzes (JSON so they are easy to extend). */
const quizzes = defineCollection({
  loader: glob({ pattern: '*.json', base: './src/content/quizzes', generateId: ({ data }) => String(data.id) }),
  schema: z.object({
    id: z.string(),
    studio: studioKey,
    week: z.number().int(),
    title: z.string(),
    questions: z.array(questionSchema).min(5),
  }),
});

/** Studio exams: a question pool from which `draw` questions are sampled. */
const exams = defineCollection({
  loader: glob({ pattern: '*.json', base: './src/content/exams', generateId: ({ data }) => String(data.id) }),
  schema: z
    .object({
      id: z.string(),
      studio: studioKey,
      title: z.string(),
      draw: z.number().int().default(20),
      timeLimitMinutes: z.number().int().default(40),
      passing: z.number().min(0).max(1).default(0.8),
      questions: z.array(questionSchema),
    })
    .refine((e) => e.questions.length >= e.draw, { message: 'Exam pool must be at least `draw` questions' }),
});

/** Studio projects and the capstone. The MDX body is the project brief. */
const projects = defineCollection({
  loader: glob({ pattern: '*.mdx', base: './src/content/projects', generateId: ({ data }) => String(data.id) }),
  schema: z.object({
    id: z.string(),
    studio: studioKey,
    title: z.string(),
    summary: z.string(),
    estHours: z.number(),
    /** Suggested name for the separate GitHub repo you build this in. */
    repoName: z.string(),
    requirements: z.array(
      z.object({ id: z.string(), text: z.string(), required: z.boolean().default(true) }),
    ),
    rubric: z.array(
      z.object({
        id: z.string(),
        criterion: z.string(),
        levels: z.object({ 1: z.string(), 2: z.string(), 3: z.string(), 4: z.string() }),
      }),
    ),
    milestones: z
      .array(z.object({ id: z.string(), title: z.string(), week: z.number(), deliverables: z.array(z.string()) }))
      .default([]),
    defense: z.array(z.object({ id: z.string(), text: z.string() })).default([]),
    sources: z.array(sourceRef).default([]),
  }),
});

/**
 * Every external source the course draws on, with its license. Generates CREDITS.md.
 * Sources may be split across several YAML files in src/content/sources/
 * (each a list of entries); ids must be unique across all of them.
 */
const sources = defineCollection({
  loader: async () => {
    const fs = await import('node:fs/promises');
    const { parse } = await import('yaml');
    const dir = './src/content/sources';
    const files = (await fs.readdir(dir)).filter((f) => f.endsWith('.yaml')).sort();
    const seen = new Map<string, string>();
    const entries: Record<string, unknown>[] = [];
    for (const f of files) {
      const list = parse(await fs.readFile(`${dir}/${f}`, 'utf8')) ?? [];
      for (const item of list) {
        if (seen.has(item.id)) throw new Error(`Duplicate source id "${item.id}" in ${f} (already in ${seen.get(item.id)})`);
        seen.set(item.id, f);
        entries.push(item);
      }
    }
    return entries as { id: string }[];
  },
  schema: z.object({
    id: z.string(),
    title: z.string(),
    author: z.string(),
    url: z.url(),
    license: z.string(),
    licenseUrl: z.url().optional(),
    /**
     * adapt = license permits adaptation with attribution
     * summarize = copyrighted; link and summarize in our own words only
     * embed = video; embed via official player and link, never rehost
     */
    policy: z.enum(['adapt', 'summarize', 'embed']),
    kind: z.enum(['course', 'docs', 'paper', 'book', 'blog', 'video', 'repo', 'report']),
    notes: z.string().optional(),
  }),
});

export const collections = { studios, lessons, quizzes, exams, projects, sources };
