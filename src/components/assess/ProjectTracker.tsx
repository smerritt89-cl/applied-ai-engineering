/**
 * Project workspace (Preact island): requirements checklist, milestones,
 * self-assessment rubric (1 to 4 per criterion), defense checklist, links to
 * your separate project repo and demo, and a "mark submitted" switch.
 *
 * Everything autosaves to your progress. The rubric score feeds 40% of the
 * studio grade (see src/lib/grading.ts).
 */
import { projectDraft, update } from '../../lib/progress';
import { useProgress } from '../../lib/useProgress';
import { pct, projectScore, letter } from '../../lib/grading';

interface Props {
  id: string;
  repoName: string;
  githubUser: string;
  requirements: { id: string; text: string; required: boolean }[];
  rubric: { id: string; criterion: string; levels: Record<'1' | '2' | '3' | '4', string> }[];
  milestones: { id: string; title: string; week: number; deliverables: string[] }[];
  defense: { id: string; text: string }[];
  /** Which part of the tracker to render; lets the page interleave it with the brief. */
  section: 'checklist' | 'milestones' | 'rubric' | 'defense' | 'submit';
}

const LEVEL_NAMES = { 1: 'Beginning', 2: 'Developing', 3: 'Proficient', 4: 'Exemplary' } as const;

export default function ProjectTracker(props: Props) {
  const state = useProgress();
  const p = state?.projects[props.id];
  const set = (fn: (d: ReturnType<typeof projectDraft>) => void) => update((s) => fn(projectDraft(s, props.id)));

  if (!state) return <div class="card muted small">Loading your progress…</div>;

  if (props.section === 'checklist') {
    const req = props.requirements;
    const done = req.filter((r) => p?.checklist[r.id]).length;
    return (
      <div class="card">
        <p class="small muted" style="margin-top:0">{done} of {req.length} done · items marked <em>stretch</em> are optional</p>
        <ul class="checklist">
          {req.map((r) => (
            <li key={r.id}>
              <label>
                <input type="checkbox" checked={Boolean(p?.checklist[r.id])} onChange={(e) => set((d) => (d.checklist[r.id] = (e.currentTarget as HTMLInputElement).checked))} />
                <span>{r.text} {!r.required && <span class="pill">stretch</span>}</span>
              </label>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  if (props.section === 'milestones') {
    return (
      <div class="stack">
        {props.milestones.map((m) => (
          <div class="card" key={m.id}>
            <label class="row" style="justify-content:space-between">
              <span><span class="eyebrow">Week {m.week}</span><br /><strong>{m.title}</strong></span>
              <span class="row small" style="font-weight:400">
                <input type="checkbox" checked={Boolean(p?.milestones[m.id])} onChange={(e) => set((d) => (d.milestones[m.id] = (e.currentTarget as HTMLInputElement).checked))} />
                Done
              </span>
            </label>
            <ul class="small">{m.deliverables.map((x) => <li key={x}>{x}</li>)}</ul>
          </div>
        ))}
      </div>
    );
  }

  if (props.section === 'rubric') {
    const score = projectScore(p?.rubric, props.rubric.map((r) => r.id));
    return (
      <div class="card">
        <p class="small muted" style="margin-top:0">
          Score yourself honestly against the descriptions, ideally after a day away from the code. Current project score:{' '}
          <strong>{score === null ? 'not scored' : `${pct(score)} (${letter(score)})`}</strong>
        </p>
        <table class="rubric">
          <thead>
            <tr>
              <th scope="col">Criterion</th>
              {([1, 2, 3, 4] as const).map((l) => <th scope="col" key={l}>{l} · {LEVEL_NAMES[l]}</th>)}
            </tr>
          </thead>
          <tbody>
            {props.rubric.map((r) => (
              <tr key={r.id}>
                <th scope="row">{r.criterion}</th>
                {([1, 2, 3, 4] as const).map((l) => (
                  <td key={l}>
                    <label>
                      <input
                        type="radio"
                        name={`rub-${r.id}`}
                        checked={p?.rubric[r.id] === l}
                        onChange={() => set((d) => (d.rubric[r.id] = l))}
                        aria-label={`${r.criterion}: level ${l}, ${LEVEL_NAMES[l]}`}
                      />{' '}
                      {r.levels[String(l) as '1']}
                    </label>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (props.section === 'defense') {
    return (
      <div class="card">
        <ul class="checklist">
          {props.defense.map((x) => (
            <li key={x.id}>
              <label>
                <input type="checkbox" checked={Boolean(p?.defense[x.id])} onChange={(e) => set((d) => (d.defense[x.id] = (e.currentTarget as HTMLInputElement).checked))} />
                <span>{x.text}</span>
              </label>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  // section === 'submit'
  const missingReq = props.requirements.filter((r) => r.required && !p?.checklist[r.id]).length;
  const missingRubric = props.rubric.filter((r) => !p?.rubric[r.id]).length;
  const suggested = `https://github.com/${props.githubUser}/${props.repoName}`;
  return (
    <div class="card stack">
      <div>
        <label for={`repo-${props.id}`}>Project repo URL</label>
        <br />
        <input id={`repo-${props.id}`} type="url" style="width:100%" placeholder={suggested} value={p?.repoUrl ?? ''} onChange={(e) => set((d) => (d.repoUrl = (e.currentTarget as HTMLInputElement).value.trim()))} />
      </div>
      <div>
        <label for={`demo-${props.id}`}>Demo or write-up URL (optional)</label>
        <br />
        <input id={`demo-${props.id}`} type="url" style="width:100%" placeholder="https://..." value={p?.demoUrl ?? ''} onChange={(e) => set((d) => (d.demoUrl = (e.currentTarget as HTMLInputElement).value.trim()))} />
      </div>
      <div>
        <label for={`notes-${props.id}`}>Notes to future you</label>
        <br />
        <textarea id={`notes-${props.id}`} rows={3} style="width:100%" value={p?.notes ?? ''} onChange={(e) => set((d) => (d.notes = (e.currentTarget as HTMLTextAreaElement).value))} />
      </div>
      <div class="row">
        {p?.submittedAt ? (
          <>
            <span class="pill pill-success">Submitted {new Date(p.submittedAt).toLocaleDateString()}</span>
            <button type="button" class="btn btn-small" onClick={() => set((d) => delete d.submittedAt)}>Reopen</button>
          </>
        ) : (
          <button
            type="button"
            class="btn btn-primary"
            disabled={missingReq > 0 || missingRubric > 0 || !p?.repoUrl}
            onClick={() => set((d) => (d.submittedAt = new Date().toISOString()))}
          >
            Mark project submitted
          </button>
        )}
        {!p?.submittedAt && (missingReq > 0 || missingRubric > 0 || !p?.repoUrl) && (
          <span class="small muted">
            Still needed: {[missingReq && `${missingReq} required checklist item(s)`, missingRubric && `${missingRubric} rubric score(s)`, !p?.repoUrl && 'a repo URL'].filter(Boolean).join(', ')}.
          </span>
        )}
      </div>
    </div>
  );
}
