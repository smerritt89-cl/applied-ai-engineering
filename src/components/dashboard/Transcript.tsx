/**
 * Transcript: one row per studio with quiz, exam, and project scores, the
 * weighted grade, and status, plus a list of completed projects with links.
 * Printable (use the browser's Print / Save as PDF).
 */
import { useProgress } from '../../lib/useProgress';
import { letter, pct, summarizeStudio, totalHours, WEIGHTS, type StudioStructure } from '../../lib/grading';

interface Row extends StudioStructure { label: string; projectTitle?: string; projectHref?: string }

export default function Transcript({ studios }: { studios: Row[] }) {
  const p = useProgress();
  if (!p) return <div class="card muted">Loading your transcript…</div>;
  const rows = studios.map((s) => ({ s, sum: summarizeStudio(s, p) }));
  const graded = rows.filter((r) => r.sum.complete && r.sum.grade !== null);
  const gpaLike = graded.length ? graded.reduce((a, r) => a + r.sum.grade!, 0) / graded.length : null;
  const hours = totalHours(p);
  const completedProjects = rows.filter((r) => r.s.projectId && p.projects[r.s.projectId]?.submittedAt);

  return (
    <div class="stack">
      <div class="card">
        <div class="stats">
          <div class="stat"><span class="stat-value">{graded.length}</span><span class="stat-label">Studios completed</span></div>
          <div class="stat"><span class="stat-value">{gpaLike === null ? '–' : `${pct(gpaLike)} · ${letter(gpaLike)}`}</span><span class="stat-label">Average of completed studios</span></div>
          <div class="stat"><span class="stat-value">{hours.total.toFixed(1)}</span><span class="stat-label">Total hours</span></div>
          <div class="stat"><span class="stat-value">{completedProjects.length}</span><span class="stat-label">Projects submitted</span></div>
        </div>
      </div>

      <div class="card">
        <table class="transcript-table">
          <thead>
            <tr>
              <th scope="col">Course</th>
              <th scope="col" class="num">Lessons</th>
              <th scope="col" class="num">Quizzes ({WEIGHTS.quizzes * 100}%)</th>
              <th scope="col" class="num">Exam ({WEIGHTS.exam * 100}%)</th>
              <th scope="col" class="num">Project ({WEIGHTS.project * 100}%)</th>
              <th scope="col" class="num">Grade</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ s, sum }) => (
              <tr key={s.id}>
                <th scope="row">
                  <span class="eyebrow">{s.label}</span>
                  <br />
                  {s.title}
                </th>
                <td class="num">{s.lessonIds.length ? `${sum.lessonsDone}/${sum.lessonsTotal}` : '–'}</td>
                <td class="num">{s.quizIds.length ? `${pct(sum.quizScore)} (${sum.quizzesTaken}/${s.quizIds.length})` : '–'}</td>
                <td class="num">{s.examId ? pct(sum.examScore) : '–'}{sum.examScore !== null && !sum.examPassed && ' ✗'}</td>
                <td class="num">{s.projectId ? pct(sum.projectScore) : '–'}</td>
                <td class="num"><strong>{sum.grade === null ? '–' : `${pct(sum.grade)} ${letter(sum.grade)}`}</strong></td>
                <td>
                  {s.status !== 'available' && s.lessonIds.length === 0 ? (
                    <span class="pill">Not yet available</span>
                  ) : sum.complete ? (
                    <span class="pill pill-success">Complete</span>
                  ) : sum.lessonsDone > 0 || sum.grade !== null ? (
                    <span class="pill pill-accent">In progress{sum.grade !== null ? ' (provisional)' : ''}</span>
                  ) : (
                    <span class="pill">Not started</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p class="small muted">
          Exam pass mark is 80%; ✗ marks a best attempt below it. A studio is complete when every lesson and quiz is done, the exam is passed,
          and the project is submitted. Grades for in-progress studios are provisional, weighted over what you have attempted.
        </p>
      </div>

      <div class="card">
        <h2 style="margin-top:0">Portfolio projects</h2>
        {completedProjects.length === 0 ? (
          <p class="muted">No projects submitted yet. Each studio ends with one; they appear here with links to your repos.</p>
        ) : (
          <ul>
            {completedProjects.map(({ s, sum }) => {
              const pr = p.projects[s.projectId!];
              return (
                <li key={s.id}>
                  <strong>{s.projectTitle}</strong> ({s.label}): rubric {pct(sum.projectScore)}.{' '}
                  {pr.repoUrl && <a href={pr.repoUrl}>Repo</a>}
                  {pr.demoUrl && <> · <a href={pr.demoUrl}>Demo / write-up</a></>}
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <div class="row no-print">
        <button type="button" class="btn" onClick={() => window.print()}>Print or save as PDF</button>
      </div>
    </div>
  );
}
