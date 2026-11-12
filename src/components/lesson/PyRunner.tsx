/**
 * In-browser Python exercise (Preact island, powered by Pyodide).
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

  // Restore your last edit for this exercise (per-browser convenience only).
  useEffect(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) setCode(saved);
    } catch {}
    const lessonId = root.current?.closest<HTMLElement>('[data-lesson-id]')?.dataset.lessonId;
    if (lessonId && load().lessons[lessonId]?.exercises[id]) setPassedBefore(true);
  }, []);

  const save = (v: string) => {
    setCode(v);
    try { localStorage.setItem(storageKey, v); } catch {}
  };

  const exec = async (withTests: boolean) => {
    setOut([]);
    setStatus(firstRun.current ? 'loading' : 'running');
    const lines: { text: string; err?: boolean }[] = [];
    const res = await runPython(code, {
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
      const lessonId = root.current?.closest<HTMLElement>('[data-lesson-id]')?.dataset.lessonId;
      if (lessonId) recordExercise(lessonId, id);
      setPassedBefore(true);
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

  return (
    <div class="activity" ref={root}>
      <div class="row" style="justify-content:space-between">
        <div class="activity-label">Python exercise · runs in your browser</div>
        {passedBefore && <span class="pill pill-success">Passed</span>}
      </div>
      <h3>{title}</h3>
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
        <button type="button" class="btn btn-ghost" disabled={busy} onClick={() => { save(starter.trim() + '\n'); setOut([]); setStatus('idle'); }}>Reset</button>
        {solution && (
          <button type="button" class="btn btn-ghost" onClick={() => setShowSolution(!showSolution)} aria-expanded={showSolution}>
            {showSolution ? 'Hide solution' : 'Show solution'}
          </button>
        )}
        {status === 'loading' && <span class="small muted">Loading Python (first run downloads about 10 MB)…</span>}
        {status === 'running' && <span class="small muted">Running…</span>}
      </div>
      <div class="output" role="log" aria-live="polite" aria-label="Program output" style="margin-top:10px">
        {out.map((l, i) => (
          <div key={i} class={l.err ? 'err' : ''}>{l.text}</div>
        ))}
      </div>
      {showSolution && solution && (
        <pre style="margin-top:10px"><code>{solution.trim()}</code></pre>
      )}
    </div>
  );
}
