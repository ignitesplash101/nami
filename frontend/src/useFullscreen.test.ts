import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createRef } from "react";
import { fullscreenChartHeight, useFullscreen } from "./useFullscreen";

describe("useFullscreen", () => {
  it("reports unsupported where the Fullscreen API is absent (jsdom, iPhone Safari)", () => {
    // jsdom has no document.fullscreenEnabled — exactly the environment where
    // the affordance must hide instead of rendering a dead button.
    const ref = createRef<HTMLDivElement>();
    const { result } = renderHook(() => useFullscreen(ref));
    expect(result.current.supported).toBe(false);
    expect(result.current.isFullscreen).toBe(false);
    // toggle on an unsupported/unattached ref is a safe no-op
    expect(() => result.current.toggle()).not.toThrow();
  });
});

describe("fullscreenChartHeight", () => {
  it("passes the base straight through when not fullscreen", () => {
    expect(fullscreenChartHeight(false, 360, 900)).toBe(360);
  });

  it("computes max(420, h - 260) from an explicit viewport height", () => {
    expect(fullscreenChartHeight(true, 360, 900)).toBe(640);
  });

  it("floors at 420 for a short viewport", () => {
    expect(fullscreenChartHeight(true, 360, 500)).toBe(420);
  });

  it("falls back to window.innerHeight when no viewport height is given", () => {
    const original = Object.getOwnPropertyDescriptor(window, "innerHeight");
    Object.defineProperty(window, "innerHeight", { value: 900, configurable: true });
    try {
      expect(fullscreenChartHeight(true, 360)).toBe(640);
    } finally {
      if (original) Object.defineProperty(window, "innerHeight", original);
    }
  });

  it("never returns NaN — falls back to the 800 default when window.innerHeight is unavailable", () => {
    const original = Object.getOwnPropertyDescriptor(window, "innerHeight");
    Object.defineProperty(window, "innerHeight", { value: undefined, configurable: true });
    try {
      expect(fullscreenChartHeight(true, 360)).toBe(540);
    } finally {
      if (original) Object.defineProperty(window, "innerHeight", original);
    }
  });
});
