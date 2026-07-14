import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { BOOT_RETRY_DELAYS_MS, retryBootGet, settleActiveBootEffect } from "./boot";

function networkError(): ApiError {
  return new ApiError({ status: null, detail: "Network request failed.", kind: "network" });
}

describe("retryBootGet", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("recovers when a transient network failure succeeds on a later attempt", async () => {
    const operation = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(networkError())
      .mockResolvedValue("loaded");

    const result = retryBootGet(operation);
    await vi.advanceTimersByTimeAsync(BOOT_RETRY_DELAYS_MS[0]);

    await expect(result).resolves.toBe("loaded");
    expect(operation).toHaveBeenCalledTimes(2);
  });

  it("uses two bounded delays and stops after three total attempts", async () => {
    const operation = vi.fn<() => Promise<string>>().mockRejectedValue(networkError());
    const result = retryBootGet(operation);
    const rejection = expect(result).rejects.toMatchObject({ kind: "network" });

    expect(operation).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(BOOT_RETRY_DELAYS_MS[0] - 1);
    expect(operation).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(operation).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(BOOT_RETRY_DELAYS_MS[1] - 1);
    expect(operation).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);

    await rejection;
    expect(operation).toHaveBeenCalledTimes(3);
    expect(BOOT_RETRY_DELAYS_MS).toEqual([400, 800]);
  });

  it("does not retry an HTTP or coded API error", async () => {
    const error = new ApiError({ status: 503, detail: "Unavailable", kind: "unavailable" });
    const operation = vi.fn<() => Promise<string>>().mockRejectedValue(error);

    await expect(retryBootGet(operation)).rejects.toBe(error);
    expect(operation).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("settleActiveBootEffect", () => {
  it("does not report a rejection after the owning boot effect was abandoned", async () => {
    let reject!: (reason: unknown) => void;
    const pending = new Promise<string>((_resolve, rejectPromise) => {
      reject = rejectPromise;
    });
    let active = true;
    const onSuccess = vi.fn();
    const onFailure = vi.fn();

    const settled = settleActiveBootEffect(pending, () => active, onSuccess, onFailure);
    active = false;
    reject(new Error("saved scenario load failed"));
    await settled;

    expect(onSuccess).not.toHaveBeenCalled();
    expect(onFailure).not.toHaveBeenCalled();
  });
});
