import { afterEach, describe, expect, it, vi } from "vitest";
import { scrollBehavior } from "./motion";

function stubMatchMedia(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches }))
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("scrollBehavior", () => {
  it("returns smooth when reduced motion is not requested", () => {
    stubMatchMedia(false);
    expect(scrollBehavior()).toBe("smooth");
  });

  it("returns auto under prefers-reduced-motion: reduce", () => {
    stubMatchMedia(true);
    expect(scrollBehavior()).toBe("auto");
  });
});
