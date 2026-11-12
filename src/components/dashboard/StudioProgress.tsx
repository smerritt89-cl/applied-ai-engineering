/** Progress summary block on a studio overview page. */
import { useProgress } from '../../lib/useProgress';
import { letter, pct, summarizeStudio, type StudioStructure } from '../../lib/grading';

export default function StudioProgress({ studio }: { studio: StudioStructure }) {
  const p = useProgress();
  const sum = p ? summarizeStudio(studio, p) : null;
  const ratio = sum && sum.lessonsTotal ? sum.lessonsDone / sum.lessonsTotal : 0;
  return (
    <div class="card">
      <div class="stats">
        <div class="stat"><span class="stat-value">{sum ? `${sum.lessonsDone}/${sum.lessonsTotal}` : '–'}</span><span class="stat-label">Lessons</span></div>
        <div class="stat"><span class="stat-value">{sum ? pct(sum.quizScore) : '–'}</span><span class="stat-label">Quiz average ({sum?.quizzesTaken ?? 0}/{studio.quizIds.length})</span></div>
        <div class="stat"><span class="stat-value">{sum ? pct(sum.examScore) : '–'}</span><span class="stat-label">Exam best{sum?.examPassed ? ' · passed' : ''}</span></div>
        <div class="stat"><span class="stat-value">{sum?.grade != null ? `${pct(sum.grade)} ${letter(sum.grade)}` : '–'}</span><span class="stat-label">{sum?.complete ? 'Final grade' : 'Provisional grade'}</span></div>
      </div>
      <div class="bar" style={{ marginTop: '14px', '--bar-color': studio.accent } as any} aria-hidden="true">
        <span style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  );
}
