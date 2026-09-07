import { afterEach, describe, expect, it, vi } from "vitest";
import { cachedRequest } from "./cachedRequest";

describe("cached page reads", () => {
  afterEach(() => vi.useRealTimers());

  it("shares pending work and exposes successful data for the next mount", async () => {
    let resolve!: (value: number[]) => void;
    const request = vi.fn(() => new Promise<number[]>(done => { resolve = done; }));
    const resource = cachedRequest(request);
    expect(resource.peek()).toBeUndefined();
    const first = resource.load();
    expect(resource.load()).toBe(first);
    resolve([101, 0]);
    await first;
    expect(resource.peek()).toEqual([101, 0]);
    await expect(resource.load()).resolves.toEqual([101, 0]);
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("expires old results and retries a failed refresh without serving stale values", async () => {
    vi.useFakeTimers();
    const request = vi.fn().mockResolvedValueOnce([101])
      .mockRejectedValueOnce(new Error("Aurora unavailable"))
      .mockResolvedValueOnce([102]);
    const resource = cachedRequest(request);
    await resource.load();
    vi.advanceTimersByTime(60_000);
    expect(resource.peek()).toBeUndefined();
    await expect(resource.load()).rejects.toThrow("Aurora unavailable");
    expect(resource.peek()).toBeUndefined();
    await expect(resource.load()).resolves.toEqual([102]);
    expect(request).toHaveBeenCalledTimes(3);
  });
});
