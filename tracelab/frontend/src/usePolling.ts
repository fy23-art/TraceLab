import { useCallback, useEffect, useRef, useState } from "react";

/** Calls `fn` now and every `ms` while the tab is visible. Re-runs when `deps` change. */
export function usePolling<T>(fn: () => Promise<T>, deps: unknown[], ms = 5000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const load = useCallback(async () => {
    try {
      setData(await fnRef.current());
      setError(null);
    } catch (e) {
      setError(e as Error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const tick = () => {
      if (!cancelled && !document.hidden) void load();
    };
    tick();
    const timer = setInterval(tick, ms);
    document.addEventListener("visibilitychange", tick);
    return () => {
      cancelled = true;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, ms, load]);

  return { data, error, loading, reload: load };
}
