"use client";

// Small shared polling hook used by every dashboard panel: calls `fetcher`
// immediately on mount, then again every `intervalMs`, tracking loading /
// data / error state. Kept in one place so each panel component only needs
// to describe *what* to fetch and *how* to render it.

import { useEffect, useRef, useState } from "react";

export interface PollingState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs = 7000
): PollingState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
        const result = await fetcherRef.current();
        if (cancelled) return;
        setData(result);
        setError(null);
      } catch (cause) {
        if (cancelled) return;
        setError(
          cause instanceof Error ? cause.message : "Backend unreachable"
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    run();
    const id = setInterval(run, intervalMs);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [intervalMs]);

  return { data, loading, error };
}
