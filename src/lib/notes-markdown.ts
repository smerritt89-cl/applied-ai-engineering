/**
 * Turns lesson notes into one Markdown document, in course order.
 * Shared by the Notes page (copy/download) and folder sync.
 */
import type { LessonNote } from './progress';

export interface LessonInfo {
  id: string;
  title: string;
  week: number;
  studio: string; // "Studio 1: LLM App Fundamentals"
  href: string;
}

export interface NoteRow extends LessonInfo {
  note: LessonNote;
}

/** Notes in course order; notes for lessons that no longer exist come last. */
export function orderedNotes(notes: Record<string, LessonNote>, index: LessonInfo[]): NoteRow[] {
  const known = new Set(index.map((e) => e.id));
  const rows: NoteRow[] = index.filter((e) => notes[e.id]).map((e) => ({ ...e, note: notes[e.id] }));
  for (const [id, note] of Object.entries(notes)) {
    if (!known.has(id)) rows.push({ id, title: id, week: 0, studio: 'Other', href: '', note });
  }
  return rows;
}

/** `siteUrl`, when given, turns lesson titles into links back to the lesson. */
export function notesMarkdown(notes: Record<string, LessonNote>, index: LessonInfo[], siteUrl = ''): string {
  let out = `# Applied AI Engineering notes\n\nUpdated ${new Date().toLocaleString()}\n`;
  let studio = '';
  for (const r of orderedNotes(notes, index)) {
    if (r.studio !== studio) {
      studio = r.studio;
      out += `\n## ${studio}\n`;
    }
    const title = `${r.week ? `Week ${r.week} · ` : ''}${r.title}`;
    const heading = siteUrl && r.href ? `[${title}](${siteUrl}${r.href})` : title;
    out += `\n### ${heading}\n\n${r.note.text.trim()}\n`;
  }
  return out;
}
