/**
 * Progress store: everything you do on the platform, saved in localStorage.
 *
 * Design notes
 * - One JSON document under one key, so export/import is a single file.
 * - `version` + MIGRATIONS let the shape evolve without wiping old progress.
 * - Storage can be unavailable (private windows, blocked site data). Every
 *   access is wrapped in try/catch and falls back to an in-memory copy, so
 *   the site still works; it just won't remember.
 * - Components subscribe() to changes. Changes in another tab arrive through
 *   the browser's `storage` event.
 *
 * This module has no DOM dependencies beyond `localStorage` and `window`
 * events, which keeps it unit-testable (see tests/progress.test.ts).
 */

export const STORAGE_KEY = 'aae:v1';
export const CURRENT_VERSION = 1;

export interface QuestionAnswer {
  questionId: string;
  selected: string[]; // option ids
  score: number; // 0..1
}

export interface Attempt {
  at: string; // ISO timestamp
  score: number; // 0..1
  answers: QuestionAnswer[];
  durationSec: number;
  timed?: boolean;
}

export interface LessonProgress {
  completedAt?: string;
  secondsActive: number;
  /** Knowledge-check results: question id -> correct on first try. */
  checks: Record<string, boolean>;
  /** In-browser exercises passed: exercise id -> ISO timestamp. */
  exercises: Record<string, string>;
}

export interface ProjectProgress {
  checklist: Record<string, boolean>;
  rubric: Record<string, 1 | 2 | 3 | 4>;
  milestones: Record<string, boolean>;
  defense: Record<string, boolean>;
  repoUrl?: string;
  demoUrl?: string;
  notes?: string;
  submittedAt?: string; // you mark the project as done
}

export interface HoursEntry {
  id: string;
  date: string; // YYYY-MM-DD
  hours: number;
  studio: string;
  note: string;
}

export interface Settings {
  theme: 'system' | 'light' | 'dark';
  narrationRate: number; // 0.75 .. 2
  speechVoice?: string; // Web Speech fallback voice name
  autoTrackTime: boolean;
}

export interface ProgressState {
  version: number;
  createdAt: string;
  lessons: Record<string, LessonProgress>;
  quizzes: Record<string, Attempt[]>;
  exams: Record<string, Attempt[]>;
  projects: Record<string, ProjectProgress>;
  hours: HoursEntry[];
  settings: Settings;
}

export function emptyState(): ProgressState {
  return {
    version: CURRENT_VERSION,
    createdAt: new Date().toISOString(),
    lessons: {},
    quizzes: {},
    exams: {},
    projects: {},
    hours: [],
    settings: { theme: 'system', narrationRate: 1, autoTrackTime: true },
  };
}

/**
 * Migrations: MIGRATIONS[n] upgrades a version-n document to version n+1.
 * When you change ProgressState, bump CURRENT_VERSION and add a step here.
 */
const MIGRATIONS: Record<number, (s: any) => any> = {
  // 1: (s) => ({ ...s, version: 2, newField: [] }),
};

/** Fill in missing fields so older or hand-edited documents never crash the UI. */
function normalize(raw: any): ProgressState {
  let s = raw;
  while (s && typeof s.version === 'number' && s.version < CURRENT_VERSION && MIGRATIONS[s.version]) {
    s = MIGRATIONS[s.version](s);
  }
  const base = emptyState();
  if (!s || typeof s !== 'object') return base;
  return {
    ...base,
    ...s,
    version: CURRENT_VERSION,
    settings: { ...base.settings, ...(s.settings ?? {}) },
    lessons: s.lessons ?? {},
    quizzes: s.quizzes ?? {},
    exams: s.exams ?? {},
    projects: s.projects ?? {},
    hours: Array.isArray(s.hours) ? s.hours : [],
  };
}

/* ------------------------------------------------------------------ */
/* Storage with in-memory fallback                                     */
/* ------------------------------------------------------------------ */

let memory: ProgressState | null = null;
let storageOk: boolean | null = null;

function storageAvailable(): boolean {
  if (storageOk !== null) return storageOk;
  try {
    const k = '__aae_probe__';
    localStorage.setItem(k, '1');
    localStorage.removeItem(k);
    storageOk = true;
  } catch {
    storageOk = false;
  }
  return storageOk;
}

/** True when progress is actually persisted (shown as a warning in the UI otherwise). */
export function isPersistent(): boolean {
  return typeof window !== 'undefined' && storageAvailable();
}

export function load(): ProgressState {
  if (typeof window === 'undefined') return emptyState(); // during server render
  if (!storageAvailable()) return (memory ??= emptyState());
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? normalize(JSON.parse(raw)) : emptyState();
  } catch {
    return (memory ??= emptyState());
  }
}

function save(state: ProgressState): void {
  memory = state;
  if (!storageAvailable()) return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* quota exceeded or blocked: keep the in-memory copy */
  }
}

/* ------------------------------------------------------------------ */
/* Change notifications                                                */
/* ------------------------------------------------------------------ */

type Listener = (state: ProgressState) => void;
const listeners = new Set<Listener>();
const EVENT = 'aae:progress';

export function subscribe(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function emit(state: ProgressState) {
  for (const fn of listeners) fn(state);
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(EVENT, { detail: state }));
}

if (typeof window !== 'undefined') {
  // Another tab changed progress: reload and notify this tab's components.
  window.addEventListener('storage', (e) => {
    if (e.key === STORAGE_KEY) emit(load());
  });
}

/**
 * The one way to change progress: read, mutate a draft, save, notify.
 *   update(s => { s.lessons[id].completedAt = new Date().toISOString(); })
 */
export function update(mutator: (draft: ProgressState) => void): ProgressState {
  const draft = load();
  mutator(draft);
  save(draft);
  emit(draft);
  return draft;
}

/* ------------------------------------------------------------------ */
/* Convenience mutations used by components                            */
/* ------------------------------------------------------------------ */

export function lessonDraft(s: ProgressState, id: string): LessonProgress {
  return (s.lessons[id] ??= { secondsActive: 0, checks: {}, exercises: {} });
}

export function projectDraft(s: ProgressState, id: string): ProjectProgress {
  return (s.projects[id] ??= { checklist: {}, rubric: {}, milestones: {}, defense: {} });
}

export function setLessonComplete(id: string, done: boolean) {
  update((s) => {
    const l = lessonDraft(s, id);
    if (done) l.completedAt ??= new Date().toISOString();
    else delete l.completedAt;
  });
}

export function addLessonSeconds(id: string, seconds: number) {
  if (seconds <= 0) return;
  update((s) => {
    lessonDraft(s, id).secondsActive += Math.round(seconds);
  });
}

export function recordCheck(lessonId: string, questionId: string, correct: boolean) {
  update((s) => {
    const l = lessonDraft(s, lessonId);
    // Only the first try counts, so retrying doesn't inflate the record.
    if (!(questionId in l.checks)) l.checks[questionId] = correct;
  });
}

export function recordExercise(lessonId: string, exerciseId: string) {
  update((s) => {
    lessonDraft(s, lessonId).exercises[exerciseId] ??= new Date().toISOString();
  });
}

export function recordAttempt(kind: 'quizzes' | 'exams', id: string, attempt: Attempt) {
  update((s) => {
    (s[kind][id] ??= []).push(attempt);
  });
}

export function addHours(entry: Omit<HoursEntry, 'id'>) {
  update((s) => {
    s.hours.push({ ...entry, id: `h${Date.now().toString(36)}` });
  });
}

export function removeHours(id: string) {
  update((s) => {
    s.hours = s.hours.filter((h) => h.id !== id);
  });
}

/* ------------------------------------------------------------------ */
/* Backup                                                              */
/* ------------------------------------------------------------------ */

export function exportJson(): string {
  return JSON.stringify(load(), null, 2);
}

/** Replace all progress with an exported file. Throws on invalid input. */
export function importJson(text: string): ProgressState {
  const parsed = JSON.parse(text);
  if (!parsed || typeof parsed !== 'object' || typeof parsed.version !== 'number') {
    throw new Error('This file is not an Applied AI Engineering progress export.');
  }
  const state = normalize(parsed);
  save(state);
  emit(state);
  return state;
}

export function resetAll() {
  const state = emptyState();
  save(state);
  emit(state);
}
