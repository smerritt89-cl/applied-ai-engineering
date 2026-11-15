/**
 * /walkthroughs/<exercise-id>.json: a code walkthrough, prepared at build time.
 *
 * The <PyRunner> island fetches this when it scrolls into view. Markdown is
 * rendered and code is highlighted here, so the browser ships neither a
 * Markdown parser nor a highlighter (same approach as quiz questions).
 */
import type { APIRoute, GetStaticPaths } from 'astro';
import { getCollection, type CollectionEntry } from 'astro:content';
import { blockMd, highlightLines, prepareQuestions } from '../../lib/questions';
import type { PreparedWalkthrough } from '../../lib/walkthrough';

export const getStaticPaths: GetStaticPaths = async () => {
  const all = await getCollection('walkthroughs');
  return all.map((w) => ({ params: { id: w.data.id }, props: { w } }));
};

export const GET: APIRoute = async ({ props }) => {
  const { data } = (props as { w: CollectionEntry<'walkthroughs'> }).w;
  const code = data.code.replace(/\n+$/, '') + '\n';
  const out: PreparedWalkthrough = {
    id: data.id,
    summaryHtml: blockMd(data.summary),
    code,
    codeHtml: await highlightLines(code),
    notes: data.notes.map((n) => ({ from: n.lines[0], to: n.lines[1], title: n.title, html: blockMd(n.text) })),
    review: await prepareQuestions(data.review),
    direct: data.direct && {
      taskHtml: blockMd(data.direct.task),
      prompt: data.direct.prompt.trim(),
      checklist: data.direct.checklist,
    },
  };
  return new Response(JSON.stringify(out), { headers: { 'Content-Type': 'application/json' } });
};
