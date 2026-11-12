/**
 * Folder sync: keeps a copy of your notes (and a full progress backup) in a
 * folder on your computer, rewritten a moment after every change.
 *
 * How it works
 * - Uses the File System Access API (Chrome and Edge on desktop). You pick a
 *   folder once; the browser remembers it (the handle is kept in IndexedDB).
 * - Browsers re-ask for permission after a restart unless you chose "Allow on
 *   every visit". Until then sync is "paused" and the UI shows a Resume button
 *   (permission can only be requested from a click).
 * - Writes two files:
 *     applied-ai-engineering-notes.md   every note, in course order
 *     applied-ai-engineering-backup.json  the same file as Settings > Export
 * - Nothing leaves your computer: the files are written locally by the browser.
 */
import { exportJson, load, subscribe } from './progress';
import { notesMarkdown, type LessonInfo } from './notes-markdown';
import { url } from './paths';

export const NOTES_FILE = 'applied-ai-engineering-notes.md';
export const BACKUP_FILE = 'applied-ai-engineering-backup.json';

export type SyncStatus = 'unsupported' | 'off' | 'paused' | 'on' | 'error';
export interface SyncState {
  status: SyncStatus;
  folder?: string;
  lastWrite?: Date;
  error?: string;
}

/* ---------- Remembering the folder (IndexedDB) ---------- */

const DB = 'aae-sync';
const STORE = 'handles';
const KEY = 'notes-folder';

function db(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
async function idb<T>(mode: IDBTransactionMode, op: (s: IDBObjectStore) => IDBRequest): Promise<T> {
  const d = await db();
  return new Promise((resolve, reject) => {
    const req = op(d.transaction(STORE, mode).objectStore(STORE));
    req.onsuccess = () => resolve(req.result as T);
    req.onerror = () => reject(req.error);
  });
}
const getFolder = () => idb<any>('readonly', (s) => s.get(KEY)).catch(() => undefined);
const putFolder = (h: any) => idb('readwrite', (s) => (h ? s.put(h, KEY) : s.delete(KEY)));

/* ---------- State + listeners ---------- */

let state: SyncState = { status: 'off' };
let folder: any = null; // FileSystemDirectoryHandle
const listeners = new Set<(s: SyncState) => void>();

function setState(next: SyncState) {
  state = next;
  listeners.forEach((fn) => fn(state));
}
export function onSyncState(fn: (s: SyncState) => void): () => void {
  listeners.add(fn);
  fn(state);
  return () => listeners.delete(fn);
}

export const syncSupported = () => typeof window !== 'undefined' && 'showDirectoryPicker' in window;

/* ---------- Writing ---------- */

let index: LessonInfo[] | null = null;
async function lessonIndex(): Promise<LessonInfo[]> {
  if (!index) {
    try {
      index = await (await fetch(url('/lesson-index.json'))).json();
    } catch {
      return []; // offline: write with lesson ids instead of titles, next write fixes it
    }
  }
  return index!;
}

async function writeFile(name: string, text: string) {
  const file = await folder.getFileHandle(name, { create: true });
  const w = await file.createWritable();
  await w.write(text);
  await w.close();
}

let lastNotes = '';
let lastBackup = '';
async function writeNow(force = false) {
  if (!folder || state.status !== 'on') return;
  try {
    const p = load();
    const notesKey = JSON.stringify(p.notes);
    const backup = exportJson();
    if (force || notesKey !== lastNotes) {
      const idx = await lessonIndex();
      await writeFile(NOTES_FILE, notesMarkdown(p.notes, idx, location.origin));
      if (idx.length) lastNotes = notesKey; // without titles (offline), rewrite next time
    }
    if (force || backup !== lastBackup) {
      await writeFile(BACKUP_FILE, backup);
      lastBackup = backup;
    }
    setState({ status: 'on', folder: folder.name, lastWrite: new Date() });
  } catch (e: any) {
    // Permission revoked, folder deleted or moved, disk full...
    setState({ status: 'error', folder: folder?.name, error: e?.message ?? String(e) });
  }
}

let timer: number | undefined;
function scheduleWrite() {
  clearTimeout(timer);
  timer = window.setTimeout(() => writeNow(), 1500);
}

/* ---------- Public actions ---------- */

let started = false;
/** Call once per page. Restores the remembered folder and starts syncing if allowed. */
export async function initSync() {
  if (started) return;
  started = true;
  if (!syncSupported()) return setState({ status: 'unsupported' });
  subscribe(() => state.status === 'on' && scheduleWrite());
  window.addEventListener('pagehide', () => writeNow());
  folder = await getFolder();
  if (!folder) return setState({ status: 'off' });
  const perm = await folder.queryPermission({ mode: 'readwrite' });
  if (perm === 'granted') {
    setState({ status: 'on', folder: folder.name });
    writeNow();
  } else setState({ status: 'paused', folder: folder.name });
}

/** Pick a folder (must be called from a click). */
export async function chooseFolder() {
  try {
    folder = await (window as any).showDirectoryPicker({ id: 'aae-notes', mode: 'readwrite', startIn: 'documents' });
  } catch {
    return; // cancelled
  }
  await putFolder(folder);
  setState({ status: 'on', folder: folder.name });
  await writeNow(true);
}

/** Re-grant permission after a browser restart (must be called from a click). */
export async function resumeSync() {
  if (!folder) return chooseFolder();
  const perm = await folder.requestPermission({ mode: 'readwrite' });
  if (perm === 'granted') {
    setState({ status: 'on', folder: folder.name });
    await writeNow(true);
  }
}

/** Stop syncing. Files already written stay in the folder. */
export async function stopSync() {
  folder = null;
  await putFolder(null);
  setState({ status: 'off' });
}

/* ---------- Status widget ---------- */

const time = (d?: Date) => (d ? d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' }) : '');

/**
 * Renders sync status and the right buttons into `el`.
 * compact: one line for the notes column; full: for the Notes page.
 */
export function mountSyncStatus(el: HTMLElement, compact: boolean) {
  const btn = (label: string, onClick: () => void, primary = false) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = `btn btn-small${primary ? ' btn-primary' : ''}`;
    b.textContent = label;
    b.addEventListener('click', onClick);
    return b;
  };
  const text = (t: string) => {
    const s = document.createElement('span');
    s.textContent = t;
    return s;
  };
  onSyncState((s) => {
    const parts: Node[] = [];
    switch (s.status) {
      case 'unsupported':
        parts.push(text(compact
          ? 'Saved in this browser. Use All notes → Download to keep a copy.'
          : 'Folder sync needs Chrome or Edge on a computer. In this browser, use Download Markdown or Settings → Export.'));
        break;
      case 'off':
        parts.push(text(compact ? 'Saved in this browser. ' : 'Not syncing. Pick a folder and your notes are also written there as Markdown, plus a full progress backup, a moment after every change. '));
        parts.push(btn('Save to a folder…', chooseFolder, !compact));
        break;
      case 'paused':
        parts.push(text(`Folder sync to “${s.folder}” is paused until you allow it again. `));
        parts.push(btn('Resume', resumeSync, true));
        break;
      case 'on':
        parts.push(text(compact
          ? `✓ Synced to folder “${s.folder}”${s.lastWrite ? ` at ${time(s.lastWrite)}` : ''}`
          : `✓ Syncing to folder “${s.folder}”: ${NOTES_FILE} and ${BACKUP_FILE}.${s.lastWrite ? ` Last written ${time(s.lastWrite)}.` : ''} `));
        if (!compact) parts.push(btn('Change folder', chooseFolder), text(' '), btn('Stop syncing', stopSync));
        break;
      case 'error':
        parts.push(text(`Could not write to “${s.folder}” (${s.error}). `));
        parts.push(btn('Pick the folder again', chooseFolder, true));
        break;
    }
    el.replaceChildren(...parts);
  });
}
