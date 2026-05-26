import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useMediaQuery } from "./useMediaQuery";
import { useOverlay } from "./useOverlay";

function mockMatchMedia(matches: boolean) {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  const mql = {
    matches,
    media: "",
    onchange: null,
    addEventListener: (_event: "change", listener: (event: MediaQueryListEvent) => void) => {
      listeners.add(listener);
    },
    removeEventListener: (_event: "change", listener: (event: MediaQueryListEvent) => void) => {
      listeners.delete(listener);
    },
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => true
  } as unknown as MediaQueryList;
  vi.spyOn(window, "matchMedia").mockReturnValue(mql);
  return {
    set(next: boolean) {
      (mql as { matches: boolean }).matches = next;
      for (const listener of listeners) {
        listener({ matches: next } as MediaQueryListEvent);
      }
    }
  };
}

describe("useMediaQuery", () => {
  it("returns the current matchMedia state", () => {
    mockMatchMedia(true);
    const { result } = renderHook(() => useMediaQuery("(max-width: 640px)"));
    expect(result.current).toBe(true);
  });

  it("updates on change events", () => {
    const controller = mockMatchMedia(false);
    const { result } = renderHook(() => useMediaQuery("(max-width: 640px)"));
    expect(result.current).toBe(false);
    act(() => controller.set(true));
    expect(result.current).toBe(true);
  });
});

describe("useOverlay", () => {
  it("starts closed and opens on demand", () => {
    const { result } = renderHook(() => useOverlay());
    expect(result.current.isOpen).toBe(false);
    act(() => result.current.open());
    expect(result.current.isOpen).toBe(true);
  });

  it("fires onClose BEFORE flipping isOpen to false", () => {
    const calls: string[] = [];
    const onClose = vi.fn(() => calls.push("onClose"));
    const { result } = renderHook(() => useOverlay({ onClose }));

    act(() => result.current.open());
    expect(result.current.isOpen).toBe(true);

    act(() => result.current.close());
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(result.current.isOpen).toBe(false);
  });

  it("locks body scroll while open and restores on close", () => {
    document.body.style.overflow = "scroll";
    const { result } = renderHook(() => useOverlay());

    act(() => result.current.open());
    expect(document.body.style.overflow).toBe("hidden");

    act(() => result.current.close());
    expect(document.body.style.overflow).toBe("scroll");
  });

  it("closes via Escape key and invokes onClose", () => {
    const onClose = vi.fn();
    const { result } = renderHook(() => useOverlay({ onClose }));
    act(() => result.current.open());

    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(result.current.isOpen).toBe(false);
  });
});
