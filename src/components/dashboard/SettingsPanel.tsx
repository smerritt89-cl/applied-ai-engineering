/**
 * Settings: theme, narration, time tracking, and progress backup.
 * Backup matters: localStorage can be cleared by the browser. Export a file
 * now and then (or before switching machines) and import it to restore.
 */
import { useEffect, useRef, useState } from 'preact/hooks';
import { useProgress } from '../../lib/useProgress';
import { exportJson, importJson, resetAll, update, isPersistent } from '../../lib/progress';

export default function SettingsPanel() {
  const p = useProgress();
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [msg, setMsg] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!('speechSynthesis' in window)) return;
    const loadVoices = () => setVoices(speechSynthesis.getVoices().filter((v) => v.lang.startsWith('en')));
    loadVoices();
    speechSynthesis.addEventListener('voiceschanged', loadVoices);
    return () => speechSynthesis.removeEventListener('voiceschanged', loadVoices);
  }, []);

  if (!p) return <div class="card muted">Loading…</div>;

  const setTheme = (t: 'system' | 'light' | 'dark') => {
    update((s) => (s.settings.theme = t));
    if (t === 'system') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = t;
    window.dispatchEvent(new CustomEvent('aae:theme'));
  };

  const download = () => {
    const blob = new Blob([exportJson()], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `aae-progress-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    setMsg('Exported. Keep the file somewhere safe.');
  };

  const onImport = async (e: Event) => {
    const f = (e.currentTarget as HTMLInputElement).files?.[0];
    if (!f) return;
    if (!confirm('Replace ALL current progress with this file?')) return;
    try {
      importJson(await f.text());
      setMsg('Progress restored from file.');
    } catch (err: any) {
      setMsg(`Import failed: ${err.message}`);
    }
  };

  return (
    <div class="stack">
      <section class="card stack">
        <h2 style="margin-top:0">Appearance</h2>
        <fieldset style="border:0;padding:0;margin:0" class="row">
          <legend class="visually-hidden">Theme</legend>
          {(['system', 'light', 'dark'] as const).map((t) => (
            <label class="row" style="font-weight:400" key={t}>
              <input type="radio" name="theme" checked={p.settings.theme === t} onChange={() => setTheme(t)} />
              {t === 'system' ? 'Match my device' : t[0].toUpperCase() + t.slice(1)}
            </label>
          ))}
        </fieldset>
      </section>

      <section class="card stack">
        <h2 style="margin-top:0">Narration</h2>
        <label>
          Default speed{' '}
          <select value={String(p.settings.narrationRate)} onChange={(e) => update((s) => (s.settings.narrationRate = Number((e.currentTarget as HTMLSelectElement).value)))}>
            {[0.75, 1, 1.25, 1.5, 1.75, 2].map((r) => <option value={String(r)} key={r}>{r}×</option>)}
          </select>
        </label>
        {voices.length > 0 && (
          <label>
            Browser voice (used when a section has no generated audio){' '}
            <select value={p.settings.speechVoice ?? ''} onChange={(e) => update((s) => (s.settings.speechVoice = (e.currentTarget as HTMLSelectElement).value || undefined))}>
              <option value="">Automatic</option>
              {voices.map((v) => <option value={v.name} key={v.name}>{v.name} ({v.lang})</option>)}
            </select>
          </label>
        )}
      </section>

      <section class="card stack">
        <h2 style="margin-top:0">Time tracking</h2>
        <label class="row" style="font-weight:400">
          <input type="checkbox" checked={p.settings.autoTrackTime} onChange={(e) => update((s) => (s.settings.autoTrackTime = (e.currentTarget as HTMLInputElement).checked))} />
          Count active time on lesson pages (pauses after 90 seconds idle or when the tab is hidden)
        </label>
      </section>

      <section class="card stack">
        <h2 style="margin-top:0">Backup and restore</h2>
        {!isPersistent() && <p class="callout pitfall">Local storage is blocked here, so nothing is being saved between visits.</p>}
        <p class="small muted">Progress started {new Date(p.createdAt).toLocaleDateString()}. It lives only in this browser.</p>
        <div class="row">
          <button type="button" class="btn btn-primary" onClick={download}>Export progress (.json)</button>
          <button type="button" class="btn" onClick={() => fileRef.current?.click()}>Import from file…</button>
          <input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={onImport} />
          <button
            type="button"
            class="btn btn-ghost"
            style="color:var(--danger)"
            onClick={() => {
              if (confirm('Erase all progress in this browser? Export first if you might want it back.')) {
                resetAll();
                setMsg('All progress erased.');
              }
            }}
          >
            Reset everything
          </button>
        </div>
        {msg && <p role="status">{msg}</p>}
      </section>
    </div>
  );
}
