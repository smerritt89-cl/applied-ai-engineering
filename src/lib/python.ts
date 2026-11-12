/**
 * Main-thread client for the Pyodide worker. One shared worker per page.
 * If a run exceeds the timeout, the worker is terminated (that is the only
 * way to stop an infinite loop in WebAssembly) and a fresh one starts next time.
 */
type Handler = (msg: { type: string; text?: string; ok?: boolean; error?: string; testsPassed?: boolean }) => void;

let worker: Worker | null = null;
let nextId = 1;
const handlers = new Map<number, Handler>();

function getWorker(): Worker {
  if (worker) return worker;
  worker = new Worker(new URL('./pyodide-worker.ts', import.meta.url), { type: 'module' });
  worker.onmessage = (e) => handlers.get(e.data.id)?.(e.data);
  return worker;
}

export interface RunResult {
  ok: boolean;
  stdout: string;
  error?: string;
  testsPassed?: boolean;
  timedOut?: boolean;
}

export function runPython(
  code: string,
  opts: { tests?: string; packages?: string[]; timeoutMs?: number; onOutput?: (text: string, stream: 'stdout' | 'stderr') => void } = {},
): Promise<RunResult> {
  const id = nextId++;
  const w = getWorker();
  let stdout = '';
  return new Promise((resolve) => {
    // First run also downloads Pyodide, so allow generous time.
    const limit = opts.timeoutMs ?? 60_000;
    const timer = setTimeout(() => {
      handlers.delete(id);
      worker?.terminate();
      worker = null;
      resolve({ ok: false, stdout, error: `Stopped after ${limit / 1000}s. Is there an infinite loop?`, timedOut: true });
    }, limit);

    handlers.set(id, (msg) => {
      if (msg.type === 'stdout' || msg.type === 'stderr') {
        stdout += `${msg.text}\n`;
        opts.onOutput?.(msg.text ?? '', msg.type);
        return;
      }
      clearTimeout(timer);
      handlers.delete(id);
      resolve({ ok: Boolean(msg.ok), stdout, error: msg.error, testsPassed: msg.testsPassed });
    });
    w.postMessage({ id, code, tests: opts.tests, packages: opts.packages });
  });
}
