/**
 * Active-time tracker for lesson pages.
 *
 * Counts a second only when the tab is visible AND you interacted recently
 * (pointer, key, scroll) or media is playing. Idle tabs left open overnight
 * therefore don't inflate your hours. Time is flushed to the progress store
 * every 15 seconds and when you leave the page.
 */
import { addLessonSeconds, load } from './progress';

const IDLE_AFTER_MS = 90_000; // stop counting after 90s without interaction
const FLUSH_EVERY_S = 15;

export function startLessonTimer(lessonId: string): () => void {
  if (!load().settings.autoTrackTime) return () => {};

  let lastActivity = Date.now();
  let pending = 0;
  const bump = () => (lastActivity = Date.now());
  const events = ['pointermove', 'pointerdown', 'keydown', 'scroll', 'wheel', 'touchstart'];
  events.forEach((e) => window.addEventListener(e, bump, { passive: true }));

  const mediaPlaying = () =>
    Array.from(document.querySelectorAll('audio, video')).some((m) => !(m as HTMLMediaElement).paused) ||
    (typeof speechSynthesis !== 'undefined' && speechSynthesis.speaking) ||
    document.querySelector('iframe[data-playing="true"]') !== null;

  const flush = () => {
    if (pending > 0) {
      addLessonSeconds(lessonId, pending);
      pending = 0;
    }
  };

  const tick = window.setInterval(() => {
    const active = document.visibilityState === 'visible' && (Date.now() - lastActivity < IDLE_AFTER_MS || mediaPlaying());
    if (active) pending++;
    if (pending >= FLUSH_EVERY_S) flush();
  }, 1000);

  const onHide = () => document.visibilityState === 'hidden' && flush();
  document.addEventListener('visibilitychange', onHide);
  window.addEventListener('pagehide', flush);

  return () => {
    flush();
    clearInterval(tick);
    events.forEach((e) => window.removeEventListener(e, bump));
    document.removeEventListener('visibilitychange', onHide);
    window.removeEventListener('pagehide', flush);
  };
}
