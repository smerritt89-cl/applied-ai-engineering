/**
 * Tracks which video or narration you played most recently, so the Notes
 * column can stamp "[video 3:09]" into a note.
 *
 * Players register themselves when you press play (see Video.astro and
 * Listen.astro). Nothing here talks to YouTube directly; the Video component
 * reads the time through the embed's postMessage channel.
 */
export interface MediaSource {
  kind: 'video' | 'audio';
  title: string;
  /** Current playback position in seconds, or null if unknown. */
  time: () => number | null;
}

let active: MediaSource | null = null;

export function setActiveMedia(source: MediaSource) {
  active = source;
}

export function activeMedia(): MediaSource | null {
  return active;
}

export function formatTime(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
}
