/**
 * Code walkthrough: the default view of a <PyRunner> exercise.
 *
 * Reading order, top to bottom:
 *  1. Summary: what the code does and why it's shaped this way.
 *  2. Guided read: one note at a time (Back / Next), with the lines it explains
 *     highlighted in the code; or "Show all notes" to read them as a list.
 *  3. Run it: run the code, and run the exercise's checks against it.
 *  4. Review questions: spot the bug, compare versions, predict a change.
 *     Answering all of them marks the exercise done.
 *  5. Direct the AI (optional): write the prompt you'd give a coding assistant
 *     for a change, then compare with an example and a review checklist.
 *
 * Data comes from /walkthroughs/<id>.json (see src/pages/walkthroughs/).
 */
import type { ComponentChildren } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import type { PreparedWalkthrough } from '../../lib/walkthrough';
import QuestionCard from '../assess/QuestionCard';
import { scoreQuestion } from '../../lib/grading';

interface Props {
  w: PreparedWalkthrough;
  /** Runs code (optionally with the exercise's tests); returns output lines. */
  run: (code: string, withTests: boolean) => Promise<void>;
  busy: boolean;
  hasTests: boolean;
  onExperiment: (code: string) => void;
  onReviewed: () => void;
  /** The run output box, rendered under the Run buttons. */
  output: ComponentChildren;
}

export default function Walkthrough({ w, run, busy, hasTests, onExperiment, onReviewed, output }: Props) {
  const [step, setStep] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const [answers, setAnswers] = useState<Record<string, string[]>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const codeRef = useRef<HTMLDivElement>(null);
  const reported = useRef(false);

  // Highlight the lines of the current note (or none when listing all notes).
  const highlight = (from?: number, to?: number) => {
    const root = codeRef.current;
    if (!root) return;
    root.classList.toggle('wt-focus', from !== undefined);
    root.querySelectorAll<HTMLElement>('[data-line]').forEach((el) => {
      const n = Number(el.dataset.line);
      el.classList.toggle('wt-hl', from !== undefined && n >= from && n <= to!);
    });
  };
  useEffect(() => {
    if (showAll) return highlight();
    const n = w.notes[step];
    highlight(n.from, n.to);
    // Keep the highlighted lines in view inside the code box (not the page).
    const first = codeRef.current?.querySelector<HTMLElement>(`[data-line="${n.from}"]`);
    const box = codeRef.current?.querySelector<HTMLElement>('pre');
    if (first && box) box.scrollTop = Math.max(0, first.offsetTop - box.clientHeight / 3);
  }, [step, showAll]);

  const done = w.review.filter((q) => revealed[q.id]).length;
  const right = w.review.filter((q) => revealed[q.id] && scoreQuestion(q, answers[q.id] ?? []) === 1).length;
  useEffect(() => {
    if (done === w.review.length && !reported.current) {
      reported.current = true;
      onReviewed();
    }
  }, [done]);

  const note = w.notes[step];

  return (
    <div class="walkthrough">
      <div class="wt-summary" dangerouslySetInnerHTML={{ __html: w.summaryHtml }} />

      <h4 class="wt-h">1 · Read the code</h4>
      <div class="wt-code" ref={codeRef} dangerouslySetInnerHTML={{ __html: w.codeHtml }} />

      {!showAll ? (
        <div class="wt-note" aria-live="polite">
          <div class="wt-note-head">
            <span class="wt-badge">Note {step + 1} of {w.notes.length}</span>
            <span class="small muted">Lines {note.from === note.to ? note.from : `${note.from} to ${note.to}`}</span>
          </div>
          <h5>{note.title}</h5>
          <div dangerouslySetInnerHTML={{ __html: note.html }} />
          <div class="row" style="margin-top:8px">
            <button type="button" class="btn btn-small" disabled={step === 0} onClick={() => setStep(step - 1)}>← Back</button>
            <button type="button" class="btn btn-small btn-primary" disabled={step === w.notes.length - 1} onClick={() => setStep(step + 1)}>Next note →</button>
            <button type="button" class="btn btn-small btn-ghost" onClick={() => setShowAll(true)}>Show all notes</button>
          </div>
        </div>
      ) : (
        <div class="wt-all">
          <button type="button" class="btn btn-small btn-ghost" onClick={() => setShowAll(false)}>Back to one note at a time</button>
          <ol>
            {w.notes.map((n, i) => (
              <li key={i}>
                <button type="button" class="wt-link" onClick={() => { setStep(i); setShowAll(false); }}>
                  <strong>{n.title}</strong> <span class="small muted">(lines {n.from === n.to ? n.from : `${n.from} to ${n.to}`})</span>
                </button>
                <div dangerouslySetInnerHTML={{ __html: n.html }} />
              </li>
            ))}
          </ol>
        </div>
      )}

      <h4 class="wt-h">2 · Run it</h4>
      <div class="row">
        <button type="button" class="btn" disabled={busy} onClick={() => run(w.code, false)}>▶ Run this code</button>
        {hasTests && <button type="button" class="btn" disabled={busy} onClick={() => run(w.code, true)}>Run the checks</button>}
        <button type="button" class="btn btn-ghost" onClick={() => onExperiment(w.code)}>Experiment: edit a copy</button>
      </div>
      <p class="small muted" style="margin:6px 0 0">
        "Run the checks" runs the same tests a written answer must pass, so you can see what they verify.
        "Edit a copy" opens this code in the editor tab to change and rerun.
      </p>
      {output}

      <h4 class="wt-h">3 · Review it</h4>
      {w.review.map((q, i) => (
        <QuestionCard
          key={q.id}
          q={q}
          index={i}
          total={w.review.length}
          mode="practice"
          selected={answers[q.id] ?? []}
          revealed={revealed[q.id]}
          onChange={(sel) => setAnswers({ ...answers, [q.id]: sel })}
          onCheck={() => setRevealed({ ...revealed, [q.id]: true })}
        />
      ))}
      {done === w.review.length && (
        <p class="q-feedback right" aria-live="polite">
          <strong>{right} of {w.review.length} on the first try.</strong> Exercise marked done.
        </p>
      )}

      {w.direct && <DirectTheAI id={w.id} d={w.direct} />}
    </div>
  );
}

/** Write the prompt you'd give a coding assistant, then compare with an example and a review checklist. */
function DirectTheAI({ id, d }: { id: string; d: NonNullable<PreparedWalkthrough['direct']> }) {
  const key = `aae:direct:${id}`;
  const [draft, setDraft] = useState('');
  const [shown, setShown] = useState(false);
  useEffect(() => {
    try { setDraft(localStorage.getItem(key) ?? ''); } catch {}
  }, []);
  const save = (v: string) => {
    setDraft(v);
    try { localStorage.setItem(key, v); } catch {}
  };
  return (
    <details class="wt-direct">
      <summary><h4 class="wt-h" style="display:inline">4 · Direct the AI <span class="small muted">(optional)</span></h4></summary>
      <div dangerouslySetInnerHTML={{ __html: d.taskHtml }} />
      <label class="small" for={`direct-${id}`} style="font-weight:600">Your prompt</label>
      <textarea id={`direct-${id}`} class="notes-text" rows={5} value={draft}
        placeholder="Write what you'd tell a coding assistant (Claude Code, for example). Be specific about what should change and what must not."
        onInput={(e) => save((e.currentTarget as HTMLTextAreaElement).value)} />
      <div class="row" style="margin-top:8px">
        <button type="button" class="btn btn-small" onClick={() => setShown(!shown)} aria-expanded={shown}>
          {shown ? 'Hide the example' : 'Compare with an example prompt'}
        </button>
      </div>
      {shown && (
        <div class="wt-example">
          <p class="small" style="font-weight:600;margin-bottom:4px">An example prompt</p>
          <pre class="wt-prompt">{d.prompt}</pre>
          <p class="small" style="font-weight:600;margin:10px 0 4px">Before you accept the AI's change, check that:</p>
          <ul class="wt-checklist">
            {d.checklist.map((c, i) => (
              <li key={i}><label><input type="checkbox" /> {c}</label></li>
            ))}
          </ul>
        </div>
      )}
    </details>
  );
}
