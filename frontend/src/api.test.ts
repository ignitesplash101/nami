import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  decomposeScenarioStream,
  deriveErrorKind,
  getAccess,
  profileBook,
  runScenarioStream,
  toApiError
} from "./api";
import type { ScenarioResult } from "./types";

function jsonErrorResponse(
  status: number,
  detail: string,
  headers: Record<string, string> = {}
): Response {
  return {
    ok: false,
    status,
    statusText: "Error",
    headers: new Headers(headers),
    text: () => Promise.resolve(JSON.stringify({ detail }))
  } as unknown as Response;
}

function sseResponse(frames: string[], headers: Record<string, string> = {}): Response {
  const encoder = new TextEncoder();
  let index = 0;
  const reader = {
    read: () =>
      index < frames.length
        ? Promise.resolve({ done: false, value: encoder.encode(frames[index++]) })
        : Promise.resolve({ done: true, value: undefined })
  };
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    headers: new Headers(headers),
    body: { getReader: () => reader }
  } as unknown as Response;
}

/** A stream whose read() hangs until the request's AbortSignal fires. */
function stalledSseResponse(init: RequestInit): Response {
  const signal = init.signal as AbortSignal;
  const reader = {
    read: () =>
      new Promise((_resolve, reject) => {
        if (signal.aborted) reject(new Error("aborted"));
        signal.addEventListener("abort", () => reject(new Error("aborted")));
      })
  };
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    headers: new Headers(),
    body: { getReader: () => reader }
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("deriveErrorKind", () => {
  it("prefers a known code over the status", () => {
    expect(deriveErrorKind(429, "budget_exhausted")).toBe("budget_exhausted");
    expect(deriveErrorKind(429, "run_cap")).toBe("run_cap");
    expect(deriveErrorKind(422, "rerun_required")).toBe("rerun_required");
    expect(deriveErrorKind(503, "marking_unavailable")).toBe("marking_unavailable");
  });

  it("falls back to the status when the code is absent or unrecognized", () => {
    expect(deriveErrorKind(401, null)).toBe("auth");
    expect(deriveErrorKind(403, null)).toBe("forbidden");
    expect(deriveErrorKind(410, null)).toBe("expired");
    expect(deriveErrorKind(413, null)).toBe("too_large");
    expect(deriveErrorKind(422, null)).toBe("validation");
    expect(deriveErrorKind(429, "something-new")).toBe("rate_limited");
    expect(deriveErrorKind(503, null)).toBe("unavailable");
    expect(deriveErrorKind(500, null)).toBe("unknown");
    expect(deriveErrorKind(null, null)).toBe("network");
  });
});

describe("requestJson error mapping", () => {
  it("captures status, detail, request id, and coded kind", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonErrorResponse(429, "Daily LLM budget cap reached; try again tomorrow.", {
            "X-Error-Code": "budget_exhausted",
            "X-Request-ID": "req-123"
          })
        )
      )
    );
    const error = await getAccess().catch((exc) => exc);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.kind).toBe("budget_exhausted");
    expect(error.status).toBe(429);
    expect(error.requestId).toBe("req-123");
    expect(error.detail).toBe("Daily LLM budget cap reached; try again tomorrow.");
    expect(error.message).toBe(error.detail);
  });

  it("maps fetch rejection to a network ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    const error = await getAccess().catch((exc) => exc);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.kind).toBe("network");
    expect(error.status).toBeNull();
  });
});

describe("toApiError", () => {
  it("passes ApiError through and maps AbortError to cancelled", () => {
    const original = new ApiError({ status: 410, detail: "gone", kind: "expired" });
    expect(toApiError(original)).toBe(original);

    const abort = new Error("The operation was aborted.");
    abort.name = "AbortError";
    expect(toApiError(abort).kind).toBe("cancelled");

    expect(toApiError(new Error("boom")).kind).toBe("unknown");
    expect(toApiError(new Error("boom")).detail).toBe("boom");
  });
});

describe("runScenarioStream", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("rejects with kind timeout when the stream stalls past the idle window", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => Promise.resolve(stalledSseResponse(init)))
    );
    const promise = runScenarioStream({ scenario_text: "x" }, () => {});
    const expectation = expect(promise).rejects.toMatchObject({
      kind: "timeout",
      message: expect.stringMatching(/timed out/i)
    });
    await vi.advanceTimersByTimeAsync(60_000);
    await expectation;
  });

  it("rejects with kind cancelled when the external signal aborts", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => Promise.resolve(stalledSseResponse(init)))
    );
    const controller = new AbortController();
    const promise = runScenarioStream({ scenario_text: "x" }, () => {}, {
      signal: controller.signal
    });
    const expectation = expect(promise).rejects.toMatchObject({ kind: "cancelled" });
    controller.abort();
    await expectation;
  });

  it("maps in-band SSE error events via their code, never to network", async () => {
    const frame =
      'data: {"stage": "error", "message": "FX rate unavailable for JPY.", ' +
      '"code": "marking_unavailable"}\n\n';
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(sseResponse([frame], { "X-Request-ID": "req-sse" })))
    );
    const error = await runScenarioStream({ scenario_text: "x" }, () => {}).catch((exc) => exc);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.kind).toBe("marking_unavailable");
    expect(error.requestId).toBe("req-sse");
  });

  it("maps an un-coded SSE error event to unknown (HTTP was healthy)", async () => {
    const frame = 'data: {"stage": "error", "message": "something exploded"}\n\n';
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(sseResponse([frame]))));
    const error = await runScenarioStream({ scenario_text: "x" }, () => {}).catch((exc) => exc);
    expect(error.kind).toBe("unknown");
    expect(error.detail).toBe("something exploded");
  });

  it("resolves the final result and forwards progress events", async () => {
    const result = { result: { scenario_text: "x" } };
    const frames = [
      'data: {"stage": "market", "status": "start"}\n\n',
      `data: {"stage": "done", "result": ${JSON.stringify(result)}}\n\n`
    ];
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(sseResponse(frames))));
    const stages: string[] = [];
    const final = await runScenarioStream({ scenario_text: "x" }, (event) =>
      stages.push(event.stage)
    );
    expect(stages).toEqual(["market", "done"]);
    expect(final).toEqual(result);
  });
});

describe("decomposeScenarioStream", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("uses a 120s idle window (not the run stream's 60s)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => Promise.resolve(stalledSseResponse(init)))
    );
    let settled = false;
    const promise = decomposeScenarioStream({} as ScenarioResult, () => {}).catch((exc) => {
      settled = true;
      return exc;
    });
    await vi.advanceTimersByTimeAsync(61_000);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(60_000);
    const error = await promise;
    expect(settled).toBe(true);
    expect(error.kind).toBe("timeout");
  });

  it("reports subset progress and resolves the final result", async () => {
    const result = { result: { scenario_text: "d" } };
    const frames = [
      'data: {"stage": "subset", "done": 1, "total": 3}\n\n',
      'data: {"stage": "subset", "done": 2, "total": 3}\n\n',
      `data: {"stage": "done", "result": ${JSON.stringify(result)}}\n\n`
    ];
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(sseResponse(frames))));
    const seen: Array<[number, number]> = [];
    const final = await decomposeScenarioStream({} as ScenarioResult, (done, total) =>
      seen.push([done, total])
    );
    expect(seen).toEqual([
      [1, 3],
      [2, 3]
    ]);
    expect(final).toEqual(result);
  });
});

describe("SSE keepalives and long-request timeouts (Phase 30)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  /** Reader that delivers each frame 40s (fake time) after the previous read. */
  function pacedSseResponse(frames: string[], gapMs: number): Response {
    const encoder = new TextEncoder();
    let index = 0;
    const reader = {
      read: () => {
        if (index >= frames.length) {
          return Promise.resolve({ done: true, value: undefined });
        }
        const value = encoder.encode(frames[index++]);
        return new Promise((resolve) => {
          setTimeout(() => resolve({ done: false, value }), gapMs);
        });
      }
    };
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      headers: new Headers(),
      body: { getReader: () => reader }
    } as unknown as Response;
  }

  it("keepalive comment frames reset the 60s idle clock (bytes, not just data frames)", async () => {
    const result = { result: { scenario_text: "x" } };
    // Three 40s gaps = 120s total, twice the idle window. Only the comment
    // frames' bytes keep it alive — the old parsed-frame-only rearm would have
    // timed out at t=60s.
    const frames = [
      ": keepalive\n\n",
      ": keepalive\n\n",
      `data: {"stage": "done", "result": ${JSON.stringify(result)}}\n\n`
    ];
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(pacedSseResponse(frames, 40_000))));
    const stages: string[] = [];
    const promise = runScenarioStream({ scenario_text: "x" }, (event) => stages.push(event.stage));
    await vi.advanceTimersByTimeAsync(40_000);
    await vi.advanceTimersByTimeAsync(40_000);
    await vi.advanceTimersByTimeAsync(40_000);
    const final = await promise;
    expect(final).toEqual(result);
    expect(stages).toEqual(["done"]); // comments are never surfaced as events
  });

  it("a mid-stream connection drop carries the honest retry copy, kind network", async () => {
    const reader = {
      read: () => Promise.reject(new TypeError("network connection was lost"))
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          statusText: "OK",
          headers: new Headers(),
          body: { getReader: () => reader }
        } as unknown as Response)
      )
    );
    const error = await runScenarioStream({ scenario_text: "x" }, () => {}).catch((exc) => exc);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.kind).toBe("network");
    expect(error.detail).toMatch(/^Connection dropped mid-run/);
  });

  it("long plain requests time out with kind timeout, never network", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            const signal = init.signal as AbortSignal;
            signal.addEventListener("abort", () => {
              const abort = new Error("The operation was aborted.");
              abort.name = "AbortError";
              reject(abort);
            });
          })
      )
    );
    const promise = profileBook({ portfolio_key: "us_tech_growth" });
    const expectation = expect(promise).rejects.toMatchObject({
      kind: "timeout",
      detail: expect.stringMatching(/timed out after 240s/)
    });
    await vi.advanceTimersByTimeAsync(240_000);
    await expectation;
  });
});
