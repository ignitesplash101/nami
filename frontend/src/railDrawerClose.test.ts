import { describe, expect, it, vi } from "vitest";
import { isCompletedUnlock, wrapWithDrawerClose } from "./railDrawerClose";
import type { AccessResponse } from "./types";

function accessFixture(mode: "visitor" | "admin"): AccessResponse {
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

describe("wrapWithDrawerClose", () => {
  it("calls the wrapped fn with its original arguments", () => {
    const fn = vi.fn();
    const wrapped = wrapWithDrawerClose(fn, () => false, vi.fn());
    wrapped("us_tech_growth");
    expect(fn).toHaveBeenCalledWith("us_tech_growth");
  });

  it("closes the drawer when it is open", () => {
    const close = vi.fn();
    const wrapped = wrapWithDrawerClose(vi.fn(), () => true, close);
    wrapped("us_tech_growth");
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("is an inert no-op on close when the drawer is already closed (desktop)", () => {
    const close = vi.fn();
    const wrapped = wrapWithDrawerClose(vi.fn(), () => false, close);
    wrapped("us_tech_growth");
    expect(close).not.toHaveBeenCalled();
  });
});

describe("isCompletedUnlock", () => {
  it("is true for a successful, intentional unlock", () => {
    expect(isCompletedUnlock(accessFixture("admin"), { intentional: true })).toBe(true);
  });

  it("is false for a deliberate lock (intentional, but back to visitor)", () => {
    expect(isCompletedUnlock(accessFixture("visitor"), { intentional: true })).toBe(false);
  });

  it("is false for a silent access refresh (no intentional flag)", () => {
    expect(isCompletedUnlock(accessFixture("admin"))).toBe(false);
  });

  it("is false when opts is present but intentional is unset", () => {
    expect(isCompletedUnlock(accessFixture("admin"), {})).toBe(false);
  });
});
