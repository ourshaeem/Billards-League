/**
 * Call load(signal) now, then again intervalMs after each call finishes,
 * for as long as `enabled` is true.
 *
 * Waiting for one call to finish before scheduling the next means a slow
 * server never has requests piling up. Turning `enabled` off, a new
 * `load`, or the component going away aborts the call in flight and
 * stops the timer, so nothing sets state after a screen has closed.
 */
import { useEffect } from 'react';

export function usePolling(load, intervalMs, enabled) {
  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    let timer;

    const tick = async () => {
      await load(controller.signal);
      if (!controller.signal.aborted) {
        timer = setTimeout(tick, intervalMs);
      }
    };
    tick();

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [load, intervalMs, enabled]);
}
