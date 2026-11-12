/**
 * Build-time helpers shared by the <Listen> component and the TTS script.
 *
 * A <Listen> section's narration is identified by a hash of its normalized
 * text. Edit the prose and the hash changes, so `npm run audio` knows to
 * regenerate just that section. Unchanged sections keep their audio.
 */
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', rsquo: '’', lsquo: '‘', rdquo: '”', ldquo: '“', hellip: '…', mdash: '—', ndash: '–' };

function decode(s: string): string {
  return s
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
    .replace(/&([a-z]+);/gi, (m, n) => ENTITIES[n.toLowerCase()] ?? m);
}

/** Rendered HTML -> plain text suitable for speech. */
export function narrationText(html: string): string {
  const text = html
    // Code blocks are read as a short cue, not character by character.
    .replace(/<pre[\s\S]*?<\/pre>/gi, ' (See the code example on screen.) ')
    .replace(/<(script|style|svg)[\s\S]*?<\/\1>/gi, ' ')
    .replace(/<\/(p|li|h[1-6]|div|blockquote|tr)>/gi, '. ')
    .replace(/<br\s*\/?>/gi, ' ')
    .replace(/<[^>]+>/g, ' ');
  return decode(text)
    .replace(/\s+/g, ' ')
    .replace(/\s+([.,;:!?])/g, '$1')
    .replace(/([.!?:])\s*\.(\s|$)/g, '$1$2') // ". ." left by closing tags after punctuation
    .replace(/\.{2,}/g, '.')
    .trim();
}

export function narrationHash(text: string): string {
  return createHash('sha1').update(text).digest('hex').slice(0, 12);
}

export interface AudioEntry {
  duration: number; // seconds
  voice: string;
}

let manifest: Record<string, AudioEntry> | null = null;

/** Reads public/audio/manifest.json (written by scripts/tts/generate.py). */
export function audioFor(hash: string): AudioEntry | null {
  if (!manifest) {
    try {
      manifest = JSON.parse(fs.readFileSync(path.join(process.cwd(), 'public/audio/manifest.json'), 'utf8'));
    } catch {
      manifest = {};
    }
  }
  const entry = manifest![hash];
  if (!entry) return null;
  return fs.existsSync(path.join(process.cwd(), 'public/audio', `${hash}.mp3`)) ? entry : null;
}
