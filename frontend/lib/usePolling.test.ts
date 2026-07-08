// Tests for the shared usePolling hook: fetches immediately on mount,
// tracks loading/data/error state, and polls again on the interval.

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePolling } from "./usePolling";

/**
 * Flush the initial (non-timer, synchronous-effect-triggered) fetch's
 * pending promise without advancing virtual time -- advancing time would
 * also fire the just-registered setInterval's first tick.
 */
async function flushInitialFetch() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

describe("usePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("fetches immediately on mount and reports data with loading=false", async () => {
    const fetcher = vi.fn().mockResolvedValue({ value: 42 });

    const { result } = renderHook(() => usePolling(fetcher, 7000));

    expect(result.current.loading).toBe(true);

    await flushInitialFetch();

    expect(result.current.data).toEqual({ value: 42 });
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("sets an error string (not throwing) when the fetcher rejects", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("backend unreachable"));

    const { result } = renderHook(() => usePolling(fetcher, 7000));

    await flushInitialFetch();

    expect(result.current.error).toBe("backend unreachable");
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("polls again after intervalMs elapses", async () => {
    const fetcher = vi.fn().mockResolvedValue({ value: 1 });

    renderHook(() => usePolling(fetcher, 5000));

    await flushInitialFetch();
    expect(fetcher).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("stops polling after unmount", async () => {
    const fetcher = vi.fn().mockResolvedValue({ value: 1 });

    const { unmount } = renderHook(() => usePolling(fetcher, 5000));

    await flushInitialFetch();
    expect(fetcher).toHaveBeenCalledTimes(1);

    unmount();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1); // no further calls after unmount
  });
});
