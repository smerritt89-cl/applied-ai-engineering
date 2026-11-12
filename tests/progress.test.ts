import { beforeEach, describe, expect, it } from 'vitest';

// Minimal browser globals so progress.ts runs under Node.
class MemoryStorage {
  data = new Map<string, string>();
  getItem(k: string) { return this.data.get(k) ?? null; }
  setItem(k: string, v: string) { this.data.set(k, String(v)); }
  removeItem(k: string) { this.data.delete(k); }
  clear() { this.data.clear(); }
}
(globalThis as any).localStorage = new MemoryStorage();
(globalThis as any).window = globalThis;
(globalThis as any).addEventListener ??= () => {};
(globalThis as any).dispatchEvent ??= () => true;
(globalThis as any).CustomEvent ??= class { constructor(public type: string, public init?: any) {} };

const progress = await import('../src/lib/progress');

describe('progress store', () => {
  beforeEach(() => {
    (globalThis as any).localStorage.clear();
  });

  it('starts empty and persists updates', () => {
    expect(progress.load().lessons).toEqual({});
    progress.setLessonComplete('s1-w1-l1', true);
    expect(progress.load().lessons['s1-w1-l1'].completedAt).toBeTruthy();
    progress.setLessonComplete('s1-w1-l1', false);
    expect(progress.load().lessons['s1-w1-l1'].completedAt).toBeUndefined();
  });

  it('records only the first knowledge-check try', () => {
    progress.recordCheck('l', 'q', false);
    progress.recordCheck('l', 'q', true);
    expect(progress.load().lessons.l.checks.q).toBe(false);
  });

  it('notifies subscribers', () => {
    let calls = 0;
    const off = progress.subscribe(() => calls++);
    progress.addHours({ date: '2026-01-01', hours: 2, studio: 's1', note: 'x' });
    off();
    progress.addHours({ date: '2026-01-01', hours: 1, studio: 's1', note: 'y' });
    expect(calls).toBe(1);
    expect(progress.load().hours).toHaveLength(2);
  });

  it('round-trips export and import, and rejects junk', () => {
    progress.addLessonSeconds('l', 90);
    const json = progress.exportJson();
    progress.resetAll();
    expect(progress.load().lessons).toEqual({});
    progress.importJson(json);
    expect(progress.load().lessons.l.secondsActive).toBe(90);
    expect(() => progress.importJson('{"hello": 1}')).toThrow();
  });

  it('fills in missing fields from older or hand-edited documents', () => {
    (globalThis as any).localStorage.setItem(progress.STORAGE_KEY, JSON.stringify({ version: 1, lessons: { a: { secondsActive: 5, checks: {}, exercises: {} } } }));
    const s = progress.load();
    expect(s.hours).toEqual([]);
    expect(s.settings.theme).toBe('system');
    expect(s.lessons.a.secondsActive).toBe(5);
  });
});
