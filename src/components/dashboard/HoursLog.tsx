/**
 * Hours log. Lesson time is tracked automatically on lesson pages; project
 * work happens in other repos, so you log it here by hand.
 */
import { useState } from 'preact/hooks';
import { useProgress } from '../../lib/useProgress';
import { addHours, removeHours } from '../../lib/progress';
import { totalHours } from '../../lib/grading';

interface Props {
  studios: { id: string; label: string; title: string; lessonIds: string[] }[];
}

export default function HoursLog({ studios }: Props) {
  const p = useProgress();
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const [hours, setHours] = useState('1');
  const [studio, setStudio] = useState(studios[0]?.id ?? 's1');
  const [note, setNote] = useState('');
  if (!p) return <div class="card muted">Loading…</div>;
  const t = totalHours(p);

  const submit = (e: Event) => {
    e.preventDefault();
    const h = Number(hours);
    if (!(h > 0 && h <= 24)) return;
    addHours({ date, hours: h, studio, note: note.trim() });
    setNote('');
  };

  const perStudio = studios.map((s) => ({
    ...s,
    tracked: s.lessonIds.reduce((a, id) => a + (p.lessons[id]?.secondsActive ?? 0), 0) / 3600,
    manual: p.hours.filter((h) => h.studio === s.id).reduce((a, h) => a + h.hours, 0),
  }));

  return (
    <div class="stack">
      <div class="card">
        <div class="stats">
          <div class="stat"><span class="stat-value">{t.total.toFixed(1)}</span><span class="stat-label">Total hours</span></div>
          <div class="stat"><span class="stat-value">{t.tracked.toFixed(1)}</span><span class="stat-label">Tracked on lessons</span></div>
          <div class="stat"><span class="stat-value">{t.manual.toFixed(1)}</span><span class="stat-label">Logged (projects, labs, reading)</span></div>
        </div>
      </div>

      <form class="card stack" onSubmit={submit}>
        <h2 style="margin-top:0">Log time</h2>
        <div class="row">
          <label>Date <input type="date" value={date} max={today} onInput={(e) => setDate((e.currentTarget as HTMLInputElement).value)} required /></label>
          <label>Hours <input type="number" min="0.25" max="24" step="0.25" value={hours} onInput={(e) => setHours((e.currentTarget as HTMLInputElement).value)} required style="width:6em" /></label>
          <label>
            Studio{' '}
            <select value={studio} onChange={(e) => setStudio((e.currentTarget as HTMLSelectElement).value)}>
              {studios.map((s) => <option value={s.id} key={s.id}>{s.label}: {s.title}</option>)}
            </select>
          </label>
        </div>
        <label>
          What did you work on?
          <input type="text" value={note} onInput={(e) => setNote((e.currentTarget as HTMLInputElement).value)} placeholder="e.g. Built the extraction prompt and first eval cases" style="width:100%" />
        </label>
        <div><button type="submit" class="btn btn-primary">Add entry</button></div>
      </form>

      <div class="card">
        <h2 style="margin-top:0">By studio</h2>
        <table>
          <thead><tr><th>Studio</th><th class="num">Lessons</th><th class="num">Logged</th><th class="num">Total</th></tr></thead>
          <tbody>
            {perStudio.filter((s) => s.tracked + s.manual > 0).map((s) => (
              <tr key={s.id}><td>{s.label}: {s.title}</td><td class="num">{s.tracked.toFixed(1)}</td><td class="num">{s.manual.toFixed(1)}</td><td class="num">{(s.tracked + s.manual).toFixed(1)}</td></tr>
            ))}
          </tbody>
        </table>
        {perStudio.every((s) => s.tracked + s.manual === 0) && <p class="muted">Nothing logged yet.</p>}
      </div>

      {p.hours.length > 0 && (
        <div class="card">
          <h2 style="margin-top:0">Entries</h2>
          <table>
            <thead><tr><th>Date</th><th>Studio</th><th class="num">Hours</th><th>Note</th><th><span class="visually-hidden">Actions</span></th></tr></thead>
            <tbody>
              {p.hours.slice().sort((a, b) => b.date.localeCompare(a.date)).map((h) => (
                <tr key={h.id}>
                  <td>{h.date}</td>
                  <td>{studios.find((s) => s.id === h.studio)?.label ?? h.studio}</td>
                  <td class="num">{h.hours}</td>
                  <td>{h.note}</td>
                  <td><button type="button" class="btn btn-small btn-ghost" onClick={() => removeHours(h.id)} aria-label={`Delete entry from ${h.date}`}>Delete</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
