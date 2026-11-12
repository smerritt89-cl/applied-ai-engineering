/**
 * Build-time view of the whole program: studios with their lessons, quizzes,
 * exam and project, in display order. Pages call getProgram() instead of
 * querying collections themselves, so ordering rules live in one place.
 */
import { getCollection, type CollectionEntry } from 'astro:content';
import type { StudioStructure } from './grading';

export type Studio = CollectionEntry<'studios'>;
export type Lesson = CollectionEntry<'lessons'>;
export type Quiz = CollectionEntry<'quizzes'>;
export type Exam = CollectionEntry<'exams'>;
export type Project = CollectionEntry<'projects'>;

export interface StudioBundle {
  studio: Studio;
  lessons: Lesson[];
  weeks: { week: number; title: string; summary: string; lessons: Lesson[]; quiz?: Quiz }[];
  quizzes: Quiz[];
  exam?: Exam;
  project?: Project;
  structure: StudioStructure;
}

let cache: StudioBundle[] | null = null;

export async function getProgram(): Promise<StudioBundle[]> {
  if (cache) return cache;
  const [studios, lessons, quizzes, exams, projects] = await Promise.all([
    getCollection('studios'),
    getCollection('lessons'),
    getCollection('quizzes'),
    getCollection('exams'),
    getCollection('projects'),
  ]);

  cache = studios
    .sort((a, b) => a.data.number - b.data.number)
    .map((studio) => {
      const sid = studio.data.id;
      const ls = lessons
        .filter((l) => l.data.studio === sid)
        .sort((a, b) => a.data.week - b.data.week || a.data.order - b.data.order);
      const qs = quizzes.filter((q) => q.data.studio === sid).sort((a, b) => a.data.week - b.data.week);
      const exam = exams.find((e) => e.data.id === studio.data.exam);
      const project = projects.find((p) => p.data.id === studio.data.project);
      const weekNums = [...new Set([...studio.data.weeks.map((w) => w.week), ...ls.map((l) => l.data.week)])].sort((a, b) => a - b);
      const weeks = weekNums.map((week) => {
        const meta = studio.data.weeks.find((w) => w.week === week);
        return {
          week,
          title: meta?.title ?? `Week ${week}`,
          summary: meta?.summary ?? '',
          lessons: ls.filter((l) => l.data.week === week),
          quiz: qs.find((q) => q.data.week === week),
        };
      });
      const structure: StudioStructure = {
        id: sid,
        title: studio.data.title,
        number: studio.data.number,
        kind: studio.data.kind,
        status: studio.data.status,
        accent: studio.data.accent,
        lessonIds: ls.map((l) => l.data.id),
        quizIds: qs.map((q) => q.data.id),
        examId: exam?.data.id,
        projectId: project?.data.id,
        requiredReqIds: project?.data.requirements.filter((r) => r.required).map((r) => r.id) ?? [],
        rubricIds: project?.data.rubric.map((r) => r.id) ?? [],
      };
      return { studio, lessons: ls, weeks, quizzes: qs, exam, project, structure };
    });
  return cache;
}

/** Flat ordered list of every lesson in the program (for prev/next links). */
export async function allLessonsInOrder(): Promise<Lesson[]> {
  return (await getProgram()).flatMap((b) => b.lessons);
}

export function studioLabel(s: Studio['data']): string {
  if (s.kind === 'capstone') return 'Capstone';
  if (s.kind === 'elective') return `Elective ${s.id.slice(1)}`;
  return `Studio ${s.number}`;
}
