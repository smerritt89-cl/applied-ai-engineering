/**
 * /lesson-index.json: every lesson's id, title, week, studio, and link, in
 * course order. Folder sync fetches it to title the notes file.
 */
import type { APIRoute } from 'astro';
import { getProgram, studioLabel } from '../lib/program';
import { url } from '../lib/paths';
import type { LessonInfo } from '../lib/notes-markdown';

export const GET: APIRoute = async () => {
  const program = await getProgram();
  const index: LessonInfo[] = program.flatMap((b) =>
    b.lessons.map((l) => ({
      id: l.data.id,
      title: l.data.title,
      week: l.data.week,
      studio: `${studioLabel(b.studio.data)}: ${b.studio.data.title}`,
      href: url(`/lessons/${l.data.id}/`),
    })),
  );
  return new Response(JSON.stringify(index), { headers: { 'Content-Type': 'application/json' } });
};
