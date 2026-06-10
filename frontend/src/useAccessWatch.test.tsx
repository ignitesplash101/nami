import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AccessResponse } from "./types";
import { nextSessionExpired, useAccessWatch } from "./useAccessWatch";

const getAccessMock = vi.fn<() => Promise<AccessResponse>>();

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    getAccess: () => getAccessMock()
  };
});

function accessFixture(mode: "visitor" | "admin" = "visitor"): AccessResponse {
  return {
    access_mode: mode,
    admin_available: true,
    latest_market_date: "2026-06-09",
    permissions: {
      custom_portfolio: mode === "admin",
      free_text_scenario: mode === "admin",
      narrative_decomposition: mode === "admin"
    }
  };
}

function Watcher({
  enabled,
  intervalMs,
  onAccess
}: {
  enabled: boolean;
  intervalMs?: number;
  onAccess: (access: AccessResponse) => void;
}) {
  useAccessWatch({ enabled, intervalMs, onAccess });
  return null;
}

describe("nextSessionExpired", () => {
  it("flags only an unintentional admin→visitor downgrade", () => {
    expect(nextSessionExpired("admin", "visitor", false)).toBe(true);
    expect(nextSessionExpired("admin", "visitor", true)).toBe(false); // deliberate lock
    expect(nextSessionExpired("visitor", "visitor", false)).toBe(false);
    expect(nextSessionExpired(null, "visitor", false)).toBe(false); // initial load
    expect(nextSessionExpired("admin", "admin", false)).toBe(false);
  });
});

describe("useAccessWatch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    getAccessMock.mockReset();
    getAccessMock.mockResolvedValue(accessFixture());
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("refetches access on the interval while visible", async () => {
    const onAccess = vi.fn();
    render(<Watcher enabled intervalMs={1000} onAccess={onAccess} />);
    expect(getAccessMock).not.toHaveBeenCalled();

    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(getAccessMock).toHaveBeenCalledTimes(1);
    expect(onAccess).toHaveBeenCalledWith(accessFixture());

    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(getAccessMock).toHaveBeenCalledTimes(3);
  });

  it("does nothing while disabled", async () => {
    const onAccess = vi.fn();
    render(<Watcher enabled={false} intervalMs={1000} onAccess={onAccess} />);
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(getAccessMock).not.toHaveBeenCalled();
  });

  it("refetches when the tab becomes visible", async () => {
    const onAccess = vi.fn();
    render(<Watcher enabled intervalMs={60_000} onAccess={onAccess} />);
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(0);
    });
    // jsdom reports visibilityState "visible" by default.
    expect(getAccessMock).toHaveBeenCalledTimes(1);
  });

  it("swallows fetch failures so a blip can't fabricate a downgrade", async () => {
    const onAccess = vi.fn();
    getAccessMock.mockRejectedValue(new Error("offline"));
    render(<Watcher enabled intervalMs={1000} onAccess={onAccess} />);
    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(getAccessMock).toHaveBeenCalled();
    expect(onAccess).not.toHaveBeenCalled();
  });
});
