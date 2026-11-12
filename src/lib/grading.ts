/**
 * Grading rules, in one place so the transcript, dashboard, and quiz engine
 * agree. Pure functions only: no storage or DOM access (unit-tested).
 *
 * Policy (also shown on the Syllabus page):
 *   Studio grade = 30% weekly quizzes (mean of best attempts)
 *                + 30% studio exam (best attempt)
 *                + 40% project (self-assessed rubric)
 *   A studio is *complete* when every lesson is done, the exam is passed
 *   (>= 80%), and the project is marked submitted with every required
 *   checklist item ticked and every rubric criterion scored.
 *   Until then the grade is *provisional*: weights are renormalized over
 *   the components you have attempted.
 */
import type { Attempt, ProgressState } from './progress';

export const WEIGHTS = { quizzes: 0.3, exam: 0.3, project: 0.4 } as const;
export const EXAM_PASSING = 0.8;

/** Rubric level -> percent. A "3 = proficient" is a solid B, "4 = exemplary" is 100. */
export const RUBRIC_PERCENT: Record<1 | 2 | 3 | 4, number> = { 1: 0.55, 2: 0.7, 3: 0.85, 4: 1 };

/* ------------------------------------------------------------------ */
/* Questions                                                           */
/* ------------------------------------------------------------------ */

export interface GradableQuestion {
  id: string;
  type: string;
  options: { id: string; correct: boolean }[];
}

/**
 * Score one answer from 0 to 1.
 * - Single-answer types: 1 if the chosen option is correct, else 0.
 * - multi: partial credit = (correct picks - wrong picks) / number correct,
 *   floored at 0. Picking everything therefore earns nothing.
 */
export function scoreQuestion(q: GradableQuestion, selected: string[]): number {
  const correct = new Set(q.options.filter((o) => o.correct).map((o) => o.id));
  if (q.type !== 'multi') {
    return selected.length === 1 && correct.has(selected[0]) ? 1 : 0;
  }
  let hits = 0;
  let misses = 0;
  for (const id of new Set(selected)) (correct.has(id) ? hits++ : misses++);
  return Math.max(0, (hits - misses) / correct.size);
}

export function scoreAttempt(questions: GradableQuestion[], answers: Record<string, string[]>): number {
  if (questions.length === 0) return 0;
  const total = questions.reduce((sum, q) => sum + scoreQuestion(q, answers[q.id] ?? []), 0);
  return total / questions.length;
}

export function best(attempts: Attempt[] | undefined): number | null {
  if (!attempts || attempts.length === 0) return null;
  return Math.max(...attempts.map((a) => a.score));
}

/* ------------------------------------------------------------------ */
/* Letter grades                                                       */
/* ------------------------------------------------------------------ */

const LETTERS: [number, string][] = [
  [0.93, 'A'], [0.9, 'A-'], [0.87, 'B+'], [0.83, 'B'], [0.8, 'B-'],
  [0.77, 'C+'], [0.73, 'C'], [0.7, 'C-'], [0.6, 'D'], [0, 'F'],
];

export function letter(score: number): string {
  return LETTERS.find(([min]) => score >= min)?.[1] ?? 'F';
}

export function pct(score: number | null, digits = 0): string {
  return score === null ? '–' : `${(score * 100).toFixed(digits)}%`;
}

/* ------------------------------------------------------------------ */
/* Studio summaries                                                    */
/* ------------------------------------------------------------------ */

/** The static shape of a studio, passed from the server to client islands. */
export interface StudioStructure {
  id: string;
  title: string;
  number: number;
  kind: string;
  status: string;
  accent: string;
  lessonIds: string[];
  quizIds: string[];
  examId?: string;
  projectId?: string;
  requiredReqIds: string[]; // required checklist items of the project
  rubricIds: string[];
}

export interface StudioSummary {
  lessonsDone: number;
  lessonsTotal: number;
  quizScore: number | null; // mean of best attempts over attempted quizzes
  quizzesTaken: number;
  examScore: number | null;
  examPassed: boolean;
  projectScore: number | null;
  projectSubmitted: boolean;
  grade: number | null;
  complete: boolean;
  provisional: boolean;
  secondsActive: number;
}

export function projectScore(rubric: Record<string, number> | undefined, rubricIds: string[]): number | null {
  if (!rubric || rubricIds.length === 0) return null;
  const scored = rubricIds.filter((id) => rubric[id]);
  if (scored.length === 0) return null;
  const sum = scored.reduce((acc, id) => acc + RUBRIC_PERCENT[rubric[id] as 1 | 2 | 3 | 4], 0);
  return sum / scored.length;
}

export function summarizeStudio(s: StudioStructure, p: ProgressState): StudioSummary {
  const lessonsDone = s.lessonIds.filter((id) => p.lessons[id]?.completedAt).length;
  const secondsActive = s.lessonIds.reduce((acc, id) => acc + (p.lessons[id]?.secondsActive ?? 0), 0);

  const quizBests = s.quizIds.map((id) => best(p.quizzes[id])).filter((x): x is number => x !== null);
  const quizScore = quizBests.length ? quizBests.reduce((a, b) => a + b, 0) / quizBests.length : null;

  const examScore = s.examId ? best(p.exams[s.examId]) : null;
  const examPassed = examScore !== null && examScore >= EXAM_PASSING;

  const proj = s.projectId ? p.projects[s.projectId] : undefined;
  const pScore = projectScore(proj?.rubric, s.rubricIds);
  const checklistDone = s.requiredReqIds.every((id) => proj?.checklist[id]);
  const rubricDone = s.rubricIds.every((id) => proj?.rubric[id]);
  const projectSubmitted = Boolean(proj?.submittedAt) && checklistDone && rubricDone;

  // Weighted grade over the components that exist and have been attempted.
  const parts: [number, number][] = [];
  if (s.quizIds.length && quizScore !== null) parts.push([WEIGHTS.quizzes, quizScore]);
  if (s.examId && examScore !== null) parts.push([WEIGHTS.exam, examScore]);
  if (s.projectId && pScore !== null) parts.push([WEIGHTS.project, pScore]);
  const wsum = parts.reduce((a, [w]) => a + w, 0);
  const grade = wsum > 0 ? parts.reduce((a, [w, v]) => a + w * v, 0) / wsum : null;

  const allQuizzesTaken = quizBests.length === s.quizIds.length;
  const complete =
    s.lessonIds.length > 0 &&
    lessonsDone === s.lessonIds.length &&
    (!s.examId || examPassed) &&
    (!s.projectId || projectSubmitted) &&
    allQuizzesTaken;

  return {
    lessonsDone,
    lessonsTotal: s.lessonIds.length,
    quizScore,
    quizzesTaken: quizBests.length,
    examScore,
    examPassed,
    projectScore: pScore,
    projectSubmitted,
    grade,
    complete,
    provisional: !complete,
    secondsActive,
  };
}

/** Total hours: automatically tracked lesson time + manual log entries. */
export function totalHours(p: ProgressState): { tracked: number; manual: number; total: number } {
  const tracked = Object.values(p.lessons).reduce((a, l) => a + (l.secondsActive ?? 0), 0) / 3600;
  const manual = p.hours.reduce((a, h) => a + h.hours, 0);
  return { tracked, manual, total: tracked + manual };
}

/** Fisher–Yates with a seeded PRNG (mulberry32), so shuffles are reproducible when needed. */
export function shuffle<T>(items: T[], seed = Math.floor(Math.random() * 2 ** 31)): T[] {
  const out = items.slice();
  let t = seed >>> 0;
  const rand = () => {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/**
 * Draw `n` exam questions balanced across weeks: each week contributes
 * roughly equally, remaining slots are filled at random.
 */
export function drawBalanced<T extends { week?: number }>(pool: T[], n: number, seed?: number): T[] {
  const byWeek = new Map<number, T[]>();
  for (const q of shuffle(pool, seed)) {
    const w = q.week ?? 0;
    byWeek.set(w, [...(byWeek.get(w) ?? []), q]);
  }
  const weeks = [...byWeek.keys()];
  const per = Math.floor(n / Math.max(1, weeks.length));
  const picked: T[] = [];
  for (const w of weeks) picked.push(...byWeek.get(w)!.slice(0, per));
  const rest = shuffle(pool.filter((q) => !picked.includes(q)), seed);
  picked.push(...rest.slice(0, n - picked.length));
  return shuffle(picked.slice(0, n), seed);
}
