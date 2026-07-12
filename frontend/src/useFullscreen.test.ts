import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createRef } from "react";
import { useFullscreen } from "./useFullscreen";

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
