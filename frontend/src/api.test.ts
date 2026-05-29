import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { runScenarioStream } from "./api";

describe("runScenarioStream idle timeout", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("rejects with a friendly message when the stream stalls past the idle timeout", async () => {
    // A reader whose read() never resolves until the request's AbortSignal fires.
    const fetchMock = vi.fn((_url: string, init: RequestInit) => {
      const signal = init.signal as AbortSignal;
      const reader = {
        read: () =>
          new Promise((_resolve, reject) => {
            if (signal.aborted) reject(new Error("aborted"));
            signal.addEventListener("abort", () => reject(new Error("aborted")));
          })
      };
      return Promise.resolve({
        ok: true,
        body: { getReader: () => reader }
      } as unknown as Response);
    });
    vi.stubGlobal("fetch", fetchMock);

    const promise = runScenarioStream({ scenario_text: "x" }, () => {});
    const expectation = expect(promise).rejects.toThrow(/timed out/i);
    // Advance past the 60s idle window — the idle timer aborts the request,
    // read() rejects, and runScenarioStream surfaces the friendly message.
    await vi.advanceTimersByTimeAsync(60_000);
    await expectation;
  });
});
