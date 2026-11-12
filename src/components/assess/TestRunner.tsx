/**
 * Graded assessment runner, shared by weekly quizzes and studio exams.
 *
 * Flow: intro (rules, past attempts) -> taking -> results + review.
 * Quizzes use every question. Exams draw `draw` questions from the pool,
 * balanced across weeks, so a retake is a different paper. The optional
 * timer auto-submits when it reaches zero. Every attempt is saved; the best
 * one counts toward your grade.
 *
 * Honor system: answers ship with the page (this is a static site). Don't
 * peek in DevTools. The only person you'd be fooling is future you.
 */
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import type { PreparedQuestion } from '../../lib/questions';
import { best, drawBalanced, letter, pct, scoreAttempt, scoreQuestion } from '../../lib/grading';
import { recordAttempt, type Attempt } from '../../lib/progress';
import { useProgress } from '../../lib/useProgress';
import QuestionCard from './QuestionCard';

interface Props {
  kind: 'quizzes' | 'exams';
  id: string;
  title: string;
  questions: PreparedQuestion[];
  draw?: number;
  timeLimitMinutes?: number;
  passing?: number;
}

type Phase = 'intro' | 'taking' | 'results';

export default function TestRunner({ kind, id, title, questions: pool, draw, timeLimitMinutes, passing }: Props) {
  const progress = useProgress();
  const attempts: Attempt[] = progress?.[kind][id] ?? [];
  const isExam = kind === 'exams';
  const [phase, setPhase] = useState<Phase>('intro');
  const [paper, setPaper] = useState<PreparedQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, string[]>>({});
  const [timed, setTimed] = useState(isExam);
  const [remaining, setRemaining] = useState(0);
  const [result, setResult] = useState<Attempt | null>(null);
  const startedAt = useRef(0);
  const topRef = useRef<HTMLDivElement>(null);

  const count = isExam ? Math.min(draw ?? pool.length, pool.length) : pool.length;
  const limitSec = (timeLimitMinutes ?? 0) * 60;

  const start = () => {
    setPaper(isExam ? drawBalanced(pool, count) : pool);
    setAnswers({});
    setResult(null);
    startedAt.current = Date.now();
    setRemaining(limitSec);
    setPhase('taking');
    requestAnimationFrame(() => topRef.current?.focus());
  };

  const submit = (auto = false) => {
    const unanswered = paper.filter((q) => !(answers[q.id]?.length)).length;
    if (!auto && unanswered > 0 && !confirm(`${unanswered} question(s) unanswered. Submit anyway?`)) return;
    const attempt: Attempt = {
      at: new Date().toISOString(),
      score: scoreAttempt(paper, answers),
      answers: paper.map((q) => ({ questionId: q.id, selected: answers[q.id] ?? [], score: scoreQuestion(q, answers[q.id] ?? []) })),
      durationSec: Math.round((Date.now() - startedAt.current) / 1000),
      timed: isExam ? timed : undefined,
    };
    recordAttempt(kind, id, attempt);
    setResult(attempt);
    setPhase('results');
    requestAnimationFrame(() => topRef.current?.focus());
  };

  // Countdown for timed exams.
  useEffect(() => {
    if (phase !== 'taking' || !isExam || !timed || !limitSec) return;
    const t = setInterval(() => {
      const left = limitSec - Math.floor((Date.now() - startedAt.current) / 1000);
      setRemaining(left);
      if (left <= 0) {
        clearInterval(t);
        submit(true);
      }
    }, 1000);
    return () => clearInterval(t);
  }, [phase, timed]);

  // Warn before leaving mid-attempt.
  useEffect(() => {
    if (phase !== 'taking') return;
    const h = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener('beforeunload', h);
    return () => window.removeEventListener('beforeunload', h);
  }, [phase]);

  const answered = useMemo(() => paper.filter((q) => answers[q.id]?.length).length, [paper, answers]);
  const bestScore = best(attempts);
  const mmss = (s: number) => `${Math.floor(Math.max(0, s) / 60)}:${String(Math.max(0, s) % 60).padStart(2, '0')}`;

  return (
    <div ref={topRef} tabIndex={-1} style="outline:none">
      {phase === 'intro' && (
        <div class="card stack">
          <p>
            <strong>{count} questions</strong>
            {isExam && pool.length > count && <> drawn at random from a pool of {pool.length}</>}. Multiple choice, multi-select
            (partial credit), code reading, and scenarios.
            {passing !== undefined && <> Passing score: <strong>{pct(passing)}</strong>.</>} Your best attempt counts.
          </p>
          {isExam && limitSec > 0 && (
            <label class="row" style="font-weight:400">
              <input type="checkbox" checked={timed} onChange={(e) => setTimed((e.currentTarget as HTMLInputElement).checked)} />
              Timed: {timeLimitMinutes} minutes (auto-submits at zero)
            </label>
          )}
          <div class="row">
            <button type="button" class="btn btn-primary" onClick={start}>
              {attempts.length ? 'Start a new attempt' : 'Start'}
            </button>
            {bestScore !== null && (
              <span class="small muted">
                Best so far: <strong>{pct(bestScore)}</strong> ({letter(bestScore)}) over {attempts.length} attempt{attempts.length === 1 ? '' : 's'}
              </span>
            )}
          </div>
          {attempts.length > 0 && (
            <details>
              <summary class="small">Attempt history</summary>
              <table class="small">
                <thead><tr><th>Date</th><th>Score</th><th>Time</th>{isExam && <th>Timed</th>}</tr></thead>
                <tbody>
                  {attempts.slice().reverse().map((a) => (
                    <tr key={a.at}>
                      <td>{new Date(a.at).toLocaleString()}</td>
                      <td>{pct(a.score)}</td>
                      <td>{mmss(a.durationSec)}</td>
                      {isExam && <td>{a.timed ? 'Yes' : 'No'}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
        </div>
      )}

      {phase === 'taking' && (
        <>
          <div class="card row" style="position:sticky;top:66px;z-index:5;justify-content:space-between">
            <span>
              Answered <strong>{answered}</strong> / {paper.length}
            </span>
            {isExam && timed && limitSec > 0 && (
              <span class={`timer ${remaining < 120 ? 'low' : ''}`} role="timer" aria-live={remaining < 60 ? 'assertive' : 'off'}>
                ⏱ {mmss(remaining)}
              </span>
            )}
            <button type="button" class="btn btn-primary" onClick={() => submit()}>Submit</button>
          </div>
          <div class="card" style="margin-top:16px">
            {paper.map((q, i) => (
              <QuestionCard
                key={q.id}
                q={q}
                index={i}
                total={paper.length}
                mode="test"
                selected={answers[q.id] ?? []}
                onChange={(sel) => setAnswers((a) => ({ ...a, [q.id]: sel }))}
              />
            ))}
            <div class="row" style="margin-top:12px">
              <button type="button" class="btn btn-primary" onClick={() => submit()}>Submit {isExam ? 'exam' : 'quiz'}</button>
            </div>
          </div>
        </>
      )}

      {phase === 'results' && result && (
        <>
          <div class="card stack" aria-live="polite">
            <div class="stats">
              <div class="stat"><span class="stat-value">{pct(result.score)}</span><span class="stat-label">This attempt ({letter(result.score)})</span></div>
              <div class="stat"><span class="stat-value">{pct(best([...attempts]))}</span><span class="stat-label">Best attempt</span></div>
              <div class="stat"><span class="stat-value">{mmss(result.durationSec)}</span><span class="stat-label">Time taken</span></div>
            </div>
            {passing !== undefined && (
              <p>
                {result.score >= passing ? (
                  <span class="pill pill-success">Passed</span>
                ) : (
                  <span class="pill pill-warn">Below the {pct(passing)} pass mark</span>
                )}{' '}
                {result.score < passing && 'Review the explanations below, revisit those lessons, then try a new paper.'}
              </p>
            )}
            <div class="row">
              <button type="button" class="btn" onClick={start}>Retake</button>
              <a class="btn btn-ghost" href="#review">Jump to review</a>
            </div>
          </div>
          <div class="card" id="review" style="margin-top:16px">
            <h2 style="margin-top:0">Review</h2>
            {paper.map((q, i) => (
              <QuestionCard key={q.id} q={q} index={i} total={paper.length} mode="review" selected={answers[q.id] ?? []} />
            ))}
          </div>
        </>
      )}
      <span class="visually-hidden">{title}</span>
    </div>
  );
}
