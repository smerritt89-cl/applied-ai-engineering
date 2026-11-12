/**
 * Dashboard island: program-wide progress, "continue where you left off",
 * hours, and a card per studio. The static program structure comes from the
 * server as props; your progress is read from localStorage in the browser.
 */
import { useProgress } from '../../lib/useProgress';
import { summarizeStudio, totalHours, pct, letter, type StudioStructure } from '../../lib/grading';
import { isPersistent } from '../../lib/progress';

interface LessonRef { id: string; title: string; href: string; studio: string }
interface StudioCard extends StudioStructure { href: string; label: string; tagline: string; estWeeks: number }

interface Props {
  studios: StudioCard[];
  lessons: LessonRef[]; // every lesson in program order
}

export default function Dashboard({ studios, lessons }: Props) {
  const p = useProgress();
  const available = studios.filter((s) => s.lessonIds.length > 0);
  const totalLessons = available.reduce((a, s) => a + s.lessonIds.length, 0);
  const doneLessons = p ? lessons.filter((l) => p.lessons[l.id]?.completedAt).length : 0;
  const hours = p ? totalHours(p) : { total: 0, tracked: 0, manual: 0 };
  const next = p ? lessons.find((l) => !p.lessons[l.id]?.completedAt) : lessons[0];
  const studiosDone = p ? studios.filter((s) => s.lessonIds.length && summarizeStudio(s, p).complete).length : 0;

  // Hours in the last 7 days (manual entries only have dates; tracked time is cumulative).
  const weekAgo = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10);
  const manualThisWeek = p ? p.hours.filter((h) => h.date >= weekAgo).reduce((a, h) => a + h.hours, 0) : 0;

  return (
    <div class="stack" style="--gap:20px">
      {p && !isPersistent() && (
        <div class="callout pitfall"><div class="callout-title">Progress isn't being saved</div>This browser is blocking local storage (private window or site-data settings). Your work will be lost when you close the tab.</div>
      )}
      <div class="card">
        <div class="stats">
          <div class="stat"><span class="stat-value">{p ? `${doneLessons}/${totalLessons}` : '–'}</span><span class="stat-label">Lessons completed</span></div>
          <div class="stat"><span class="stat-value">{p ? `${studiosDone}/${studios.filter((s) => s.kind === 'studio').length}` : '–'}</span><span class="stat-label">Studios completed</span></div>
          <div class="stat"><span class="stat-value">{p ? hours.total.toFixed(1) : '–'}</span><span class="stat-label">Hours logged ({hours.tracked.toFixed(1)} tracked + {hours.manual.toFixed(1)} project)</span></div>
          <div class="stat"><span class="stat-value">{p ? manualThisWeek.toFixed(1) : '–'}</span><span class="stat-label">Project hours, last 7 days</span></div>
        </div>
        <div class="bar" style="margin-top:16px" role="progressbar" aria-label="Program progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={totalLessons ? Math.round((doneLessons / totalLessons) * 100) : 0}>
          <span style={{ width: `${totalLessons ? (doneLessons / totalLessons) * 100 : 0}%` }} />
        </div>
      </div>

      {next && (
        <div class="card row" style="justify-content:space-between">
          <div>
            <div class="eyebrow">{doneLessons === 0 ? 'Start here' : 'Continue'}</div>
            <strong>{next.title}</strong>
          </div>
          <a class="btn btn-primary" href={next.href}>{doneLessons === 0 ? 'Begin Studio 1' : 'Resume'} →</a>
        </div>
      )}

      <h2>Studios</h2>
      <div class="grid">
        {studios.map((s) => {
          const sum = p ? summarizeStudio(s, p) : null;
          const ratio = sum && sum.lessonsTotal ? sum.lessonsDone / sum.lessonsTotal : 0;
          return (
            <article class="card studio-card" style={{ '--accent-color': s.accent } as any} key={s.id}>
              <div class="row" style="justify-content:space-between">
                <span class="eyebrow">{s.label} · ~{s.estWeeks} wk</span>
                {s.status !== 'available' ? (
                  <span class="pill">Coming soon</span>
                ) : sum?.complete ? (
                  <span class="pill pill-success">Complete</span>
                ) : sum && sum.lessonsDone > 0 ? (
                  <span class="pill pill-accent">In progress</span>
                ) : null}
              </div>
              <h3><a href={s.href}>{s.title}</a></h3>
              <p class="small muted" style="margin:0">{s.tagline}</p>
              {s.lessonIds.length > 0 && (
                <>
                  <p class="small" style="margin:0">
                    {sum ? `${sum.lessonsDone}/${sum.lessonsTotal} lessons` : `${s.lessonIds.length} lessons`}
                    {sum?.grade != null && <> · grade {pct(sum.grade)} ({letter(sum.grade)}){sum.provisional ? ', provisional' : ''}</>}
                  </p>
                  <div class="bar" style={{ '--bar-color': s.accent } as any} aria-hidden="true">
                    <span style={{ width: `${ratio * 100}%` }} />
                  </div>
                </>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
