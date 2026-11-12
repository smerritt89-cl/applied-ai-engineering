/**
 * Preact hook: the current progress state, re-rendering on every change
 * (this tab or another). Returns null during the server render and the first
 * client render, so islands render a neutral placeholder rather than a
 * hydration mismatch between "no data" (server) and "your data" (browser).
 */
import { useEffect, useState } from 'preact/hooks';
import { load, subscribe, type ProgressState } from './progress';

export function useProgress(): ProgressState | null {
  const [state, setState] = useState<ProgressState | null>(null);
  useEffect(() => {
    setState(load());
    return subscribe(setState);
  }, []);
  return state;
}
