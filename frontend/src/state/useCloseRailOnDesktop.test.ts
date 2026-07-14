import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useCloseRailOnDesktop } from "./useCloseRailOnDesktop";

describe("useCloseRailOnDesktop", () => {
  it("closes the compact setup drawer when the viewport crosses to desktop", () => {
    const close = vi.fn();
    const { rerender } = renderHook(
      ({ compact }: { compact: boolean }) => useCloseRailOnDesktop(compact, close),
      { initialProps: { compact: true } }
    );

    expect(close).not.toHaveBeenCalled();
    rerender({ compact: false });
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("does not close for compact-to-compact or desktop-to-compact changes", () => {
    const close = vi.fn();
    const { rerender } = renderHook(
      ({ compact }: { compact: boolean }) => useCloseRailOnDesktop(compact, close),
      { initialProps: { compact: false } }
    );

    rerender({ compact: true });
    rerender({ compact: true });
    expect(close).not.toHaveBeenCalled();
  });
});
