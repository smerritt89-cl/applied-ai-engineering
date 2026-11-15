/**
 * In-browser Python exercise (Preact island, powered by Pyodide).
 *
 * Two views:
 *  - Walkthrough (default, when src/content/walkthroughs/<id>.yaml exists):
 *    complete annotated code to read, run, and review. See Walkthrough.tsx.
 *  - Write it yourself (optional): the original starter-code exercise.
 *
 *   <PyRunner client:visible id="count-tokens" title="Estimate tokens"
 *     starter={`def estimate(text):\n    ...`}
 *     tests={`assert estimate("") == 0, "empty string should be 0 tokens"`}
 *     solution={`...`} packages={["pydantic"]}>
 *     Instructions in Markdown.
 *   </PyRunner>
 *
 * - Run executes your code; Check runs it and then the hidden `tests` (plain
 *   asserts, whose messages are shown on failure). Passing is recorded in
 *   your progress for this lesson.
 * - Only use the standard library or Pyodide packages. Anything that needs
 *   network access, API keys, or a GPU belongs in a local lab (<LabLink>).
 */
import type { ComponentChildren } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import { runPython } from '../../lib/python';
import { recordExercise, load } from '../../lib/progress';
import { url } from '../../lib/paths';
import type { PreparedWalkthrough } from '../../lib/walkthrough';
import Walkthrough from './Walkthrough';

interface Props {
  id: string;
  title: string;
  starter: string;
  tests?: string;
  solution?: string;
  packages?: string[];
  children?: ComponentChildren;
}

type Status = 'idle' | 'loading' | 'running' | 'passed' | 'failed' | 'error';

export default function PyRunner({ id, title, starter, tests, solution, packages, children }: Props) {
  const [code, setCode] = useState(starter.trim() + '\n');
  const [out, setOut] = useState<{ text: string; err?: boolean }[]>([]);
  const [status, setStatus] = useState<Status>('idle');
  const [showSolution, setShowSolution] = useState(false);
  const [passedBefore, setPassedBefore] = useState(false);
  const firstRun = useRef(true);
  const root = useRef<HTMLDivElement>(null);
  const storageKey = `aae:code:${id}`;
  // undefined = still loading, null = no walkthrough for this exercise.
  const [walk, setWalk] = useState<PreparedWalkthrough | null | undefined>(undefined);
  const [tab, setTab] = useState<'walk' | 'write'>('walk');

  // Restore your last edit for this exercise (per-browser convenience only).
  useEffect(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) setCode(saved);
    } catch {}
    const lessonId = root.current?.closest<HTMLElement>('[data-lesson-id]')?.dataset.lessonId;
    if (lessonId && load().lessons[lessonId]?.exercises[id]) setPassedBefore(true);
    fetch(url(`/walkthroughs/${id}.json`))
      .then((r) => (r.ok ? r.json() : null))
      .then((w) => {
        setWalk(w);
        if (!w) setTab('write');
      })
      .catch(() => { setWalk(null); setTab('write'); });
  }, []);

  const markDone = () => {
    const lessonId = root.current?.closest<HTMLElement>('[data-lesson-id]')?.dataset.lessonId;
    if (lessonId) recordExercise(lessonId, id);
    setPassedBefore(true);
  };

  const save = (v: string) => {
    setCode(v);
    try { localStorage.setItem(storageKey, v); } catch {}
  };

  const exec = async (withTests: boolean, source = code, record = true) => {
    setOut([]);
    setStatus(firstRun.current ? 'loading' : 'running');
    const lines: { text: string; err?: boolean }[] = [];
    const res = await runPython(source, {
      tests: withTests ? tests : undefined,
      packages,
      timeoutMs: firstRun.current ? 90_000 : 15_000,
      onOutput: (text, stream) => {
        lines.push({ text, err: stream === 'stderr' });
        setOut([...lines]);
      },
    });
    firstRun.current = false;
    if (!res.ok) {
      const assertMsg = res.error?.match(/AssertionError:?\s*(.*)$/m)?.[1];
      lines.push({ text: withTests && assertMsg !== undefined ? `Test failed: ${assertMsg || '(no message)'}` : res.error ?? 'Error', err: true });
      setOut([...lines]);
      setStatus(withTests && assertMsg !== undefined ? 'failed' : 'error');
      return;
    }
    if (withTests) {
      lines.push({ text: '✓ All checks passed.' });
      setOut([...lines]);
      setStatus('passed');
      if (record) markDone(); // checks passing on the walkthrough's own code don't count as your answer
    } else {
      if (lines.length === 0) setOut([{ text: '(no output; use print() to see values)' }]);
      setStatus('idle');
    }
  };

  // Tab inserts four spaces; Escape leaves the editor (so keyboard users aren't trapped).
  const onKeyDown = (e: KeyboardEvent) => {
    const ta = e.currentTarget as HTMLTextAreaElement;
    if (e.key === 'Tab' && !e.shiftKey) {
      e.preventDefault();
      const { selectionStart: a, selectionEnd: b } = ta;
      const v = code.slice(0, a) + '    ' + code.slice(b);
      save(v);
      requestAnimationFrame(() => (ta.selectionStart = ta.selectionEnd = a + 4));
    } else if (e.key === 'Escape') {
      ta.blur();
    } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      exec(false);
    }
  };

  const busy = status === 'loading' || status === 'running';

  const output = (
    <div class="output" role="log" aria-live="polite" aria-label="Program output" style="margin-top:10px">
      {status === 'loading' && <div class="muted">Loading Python (first run downloads about 10 MB)…</div>}
      {status === 'running' && <div class="muted">Running…</div>}
      {out.map((l, i) => (
        <div key={i} class={l.err ? 'err' : ''}>{l.text}</div>
      ))}
    </div>
  );

  return (
    <div class="activity" ref={root}>
      <div class="row" style="justify-content:space-between">
        <div class="activity-label">{walk ? 'Code walkthrough · runs in your browser' : 'Python exercise · runs in your browser'}</div>
        {passedBefore && <span class="pill pill-success">Done</span>}
      </div>
      <h3>{title}</h3>
      {walk && (
        <div class="tabs" role="tablist" aria-label={`${title} views`}>
          <button type="button" role="tab" aria-selected={tab === 'walk'} class={tab === 'walk' ? 'tab active' : 'tab'} onClick={() => { setTab('walk'); setOut([]); }}>Walkthrough</button>
          <button type="button" role="tab" aria-selected={tab === 'write'} class={tab === 'write' ? 'tab active' : 'tab'} onClick={() => { setTab('write'); setOut([]); }}>Write it yourself <span class="muted">(optional)</span></button>
        </div>
      )}

      {walk === undefined && <p class="small muted">Loading…</p>}

      {walk && tab === 'walk' && (
        <Walkthrough
          w={walk}
          busy={busy}
          hasTests={Boolean(tests)}
          run={(src, withTests) => exec(withTests, src, false)}
          onExperiment={(src) => { save(src); setOut([]); setStatus('idle'); setTab('write'); }}
          onReviewed={markDone}
          output={output}
        />
      )}

      {walk !== undefined && tab === 'write' && (
        <>
          {children && <div class="small">{children}</div>}
          <label class="visually-hidden" for={`ed-${id}`}>Python code for {title}</label>
          <textarea
            id={`ed-${id}`}
            class="editor"
            spellcheck={false}
            value={code}
            rows={Math.min(22, Math.max(8, code.split('\n').length + 1))}
            onInput={(e) => save((e.currentTarget as HTMLTextAreaElement).value)}
            onKeyDown={onKeyDown}
            aria-describedby={`help-${id}`}
          />
          <p id={`help-${id}`} class="small muted" style="margin:4px 0 10px">
            Tab indents, Esc leaves the editor, Ctrl/⌘+Enter runs.
          </p>
          <div class="row">
            <button type="button" class="btn" disabled={busy} onClick={() => exec(false)}>▶ Run</button>
            {tests && <button type="button" class="btn btn-primary" disabled={busy} onClick={() => exec(true)}>Check my answer</button>}
            <button type="button" class="btn btn-ghost" disabled={busy} onClick={() => { save(starter.trim() + '\n'); setOut([]); setStatus('idle'); }}>Reset to starter</button>
            {solution && (
              <button type="button" class="btn btn-ghost" onClick={() => setShowSolution(!showSolution)} aria-expanded={showSolution}>
                {showSolution ? 'Hide solution' : 'Show solution'}
              </button>
            )}
          </div>
          {output}
          {showSolution && solution && (
            <pre style="margin-top:10px"><code>{solution.trim()}</code></pre>
          )}
        </>
      )}
    </div>
  );
}
