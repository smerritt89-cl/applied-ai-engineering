/// <reference lib="webworker" />
/**
 * Web Worker that runs Python with Pyodide (CPython compiled to WebAssembly).
 *
 * Running in a worker keeps the page responsive, and lets the main thread
 * kill a runaway `while True:` loop by terminating the worker.
 * Pyodide (~10 MB) is fetched from the jsDelivr CDN the first time you press
 * Run, then cached by the browser.
 *
 * Protocol (main -> worker):  { id, code, tests?, packages? }
 *           (worker -> main): { id, type: 'stdout'|'stderr', text }
 *                             { id, type: 'done', ok, error?, testsPassed? }
 */
export const PYODIDE_VERSION = '314.0.7';
const INDEX_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

let pyodidePromise: Promise<any> | null = null;
let currentId = 0;

function getPyodide() {
  pyodidePromise ??= (async () => {
    const mod = await import(/* @vite-ignore */ `${INDEX_URL}pyodide.mjs`);
    const py = await mod.loadPyodide({ indexURL: INDEX_URL });
    // Stream print() output back to the page line by line.
    py.setStdout({ batched: (text: string) => postMessage({ id: currentId, type: 'stdout', text }) });
    py.setStderr({ batched: (text: string) => postMessage({ id: currentId, type: 'stderr', text }) });
    return py;
  })();
  return pyodidePromise;
}

self.onmessage = async (event: MessageEvent) => {
  const { id, code, tests, packages } = event.data as {
    id: number;
    code: string;
    tests?: string;
    packages?: string[];
  };
  currentId = id;
  try {
    const py = await getPyodide();
    if (packages?.length) await py.loadPackage(packages);
    // Fresh namespace per run so earlier runs don't leak variables.
    const ns = py.globals.get('dict')();
    await py.runPythonAsync(code, { globals: ns });
    let testsPassed: boolean | undefined;
    if (tests) {
      await py.runPythonAsync(tests, { globals: ns });
      testsPassed = true; // tests are plain asserts: reaching here means all passed
    }
    ns.destroy();
    postMessage({ id, type: 'done', ok: true, testsPassed });
  } catch (err: any) {
    // Python exceptions arrive as PythonError with the traceback in .message.
    const msg = String(err?.message ?? err);
    const lines = msg.trim().split('\n');
    // Keep the useful tail of the traceback (skip Pyodide's internal frames).
    const userTail = lines.slice(Math.max(0, lines.findIndex((l) => l.includes('File "<exec>"')))).join('\n');
    postMessage({ id, type: 'done', ok: false, error: userTail || msg, testsPassed: tests ? false : undefined });
  }
};
