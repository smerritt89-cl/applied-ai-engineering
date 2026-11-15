/** Shape of /walkthroughs/<id>.json (built in src/pages/walkthroughs/[id].json.ts). */
import type { PreparedQuestion } from './questions';

export interface PreparedWalkthrough {
  id: string;
  summaryHtml: string;
  code: string;
  codeHtml: string;
  notes: { from: number; to: number; title: string; html: string }[];
  review: PreparedQuestion[];
  direct?: { taskHtml: string; prompt: string; checklist: string[] };
}
