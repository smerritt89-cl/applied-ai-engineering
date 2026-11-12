/**
 * Server-side (build-time) preparation of questions for the client islands.
 *
 * Questions are authored as plain strings with light inline Markdown. Here we
 * turn them into HTML once, at build time, and syntax-highlight any code with
 * Shiki, so the browser never ships a Markdown parser or highlighter.
 * Content is our own (trusted), so the islands render this HTML directly.
 */
import { codeToHtml } from 'shiki';
import type { Question } from '../content.config';

export interface PreparedOption {
  id: string;
  html: string;
  correct: boolean;
  rationaleHtml?: string;
}

export interface PreparedQuestion {
  id: string;
  type: Question['type'];
  promptHtml: string;
  codeHtml?: string;
  options: PreparedOption[];
  explanationHtml: string;
  week?: number;
  tags: string[];
}

const escapeHtml = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/** Inline Markdown subset: `code`, **bold**, *italic*, [text](url). */
export function inlineMd(src: string): string {
  const codes: string[] = [];
  // Pull code spans out first so their contents are never formatted.
  let s = src.replace(/`([^`]+)`/g, (_, c) => {
    codes.push(`<code>${escapeHtml(c)}</code>`);
    return `\u0000${codes.length - 1}\u0000`;
  });
  s = escapeHtml(s)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => codes[Number(i)]);
}

/** Paragraph-level: blank lines separate paragraphs. */
export function blockMd(src: string): string {
  return src
    .trim()
    .split(/\n\s*\n/)
    .map((p) => `<p>${inlineMd(p.replace(/\n/g, ' '))}</p>`)
    .join('');
}

export async function highlight(code: string, lang = 'python'): Promise<string> {
  return codeToHtml(code.replace(/\n$/, ''), {
    lang,
    themes: { light: 'github-light', dark: 'github-dark' },
  });
}

export async function prepareQuestions(questions: Question[]): Promise<PreparedQuestion[]> {
  return Promise.all(
    questions.map(async (q) => ({
      id: q.id,
      type: q.type,
      promptHtml: inlineMd(q.prompt),
      codeHtml: q.code ? await highlight(q.code, q.language) : undefined,
      options: q.options.map((o) => ({
        id: o.id,
        html: inlineMd(o.text),
        correct: o.correct,
        rationaleHtml: o.rationale ? inlineMd(o.rationale) : undefined,
      })),
      explanationHtml: blockMd(q.explanation),
      week: q.week,
      tags: q.tags,
    })),
  );
}
