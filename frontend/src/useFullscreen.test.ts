import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { createRef } from "react";
import type { RefObject } from "react";
import { closeExpandedCard, fullscreenChartHeight, useFullscreen } from "./useFullscreen";

describe("useFullscreen", () => {
  it("reports unsupported where the Fullscreen API is absent (jsdom, iPhone Safari)", () => {
    // jsdom has no document.fullscreenEnabled — the environment where the native
    // API is missing and the app-owned expanded-card fallback takes over.
    const ref = createRef<HTMLDivElement>();
    const { result } = renderHook(() => useFullscreen(ref));
    expect(result.current.supported).toBe(false);
    expect(result.current.isFullscreen).toBe(false);
    // toggle on an unattached ref is a safe no-op
    expect(() => result.current.toggle()).not.toThrow();
  });
});

describe("useFullscreen expanded-card fallback", () => {
  // Drives the real jsdom DOM: attach the hook's ref to a live node so the
  // effect's class/attr/scroll-lock mutations land on an actual element.
  function mountCard(surface = "contribution waterfall") {
    const node = document.createElement("div");
    node.className = "fullscreen-surface";
    document.body.appendChild(node);
    const ref: RefObject<HTMLDivElement> = { current: node };
    const view = renderHook(({ s }: { s: string }) => useFullscreen(ref, { surface: s }), {
      initialProps: { s: surface }
    });
    return { node, ref, ...view };
  }

  afterEach(() => {
    // Clear any leftover expanded state so tests don't leak the singleton.
    act(() => closeExpandedCard());
    document.body.innerHTML = "";
    document.body.style.overflow = "";
    document.documentElement.classList.remove("has-expanded-card");
  });

  it("expands the same node into a modal card (classes, html flag, isFullscreen)", () => {
    const { node, result } = mountCard();
    act(() => result.current.toggle());

    expect(node.classList.contains("is-card-expanded")).toBe(true);
    expect(node.classList.contains("fullscreen-surface")).toBe(true);
    expect(document.documentElement.classList.contains("has-expanded-card")).toBe(true);
    expect(result.current.isFullscreen).toBe(true);
  });

  it("sets dialog semantics while expanded and removes them on collapse", () => {
    const { node, result } = mountCard("diagnostics waterfall");
    act(() => result.current.toggle());

    expect(node.getAttribute("role")).toBe("dialog");
    expect(node.getAttribute("aria-modal")).toBe("true");
    expect(node.getAttribute("aria-label")).toBe("diagnostics waterfall");

    act(() => result.current.toggle());

    expect(node.hasAttribute("role")).toBe(false);
    expect(node.hasAttribute("aria-modal")).toBe(false);
    expect(node.hasAttribute("aria-label")).toBe(false);
    expect(node.classList.contains("is-card-expanded")).toBe(false);
    expect(document.documentElement.classList.contains("has-expanded-card")).toBe(false);
    expect(result.current.isFullscreen).toBe(false);
  });

  it("locks body scroll on expand and restores it on collapse", () => {
    const { result } = mountCard();
    expect(document.body.style.overflow).toBe("");
    act(() => result.current.toggle());
    expect(document.body.style.overflow).toBe("hidden");
    act(() => result.current.toggle());
    expect(document.body.style.overflow).toBe("");
  });

  it("restores body scroll when the card unmounts while expanded", () => {
    const { result, unmount } = mountCard();
    act(() => result.current.toggle());
    expect(document.body.style.overflow).toBe("hidden");
    act(() => unmount());
    expect(document.body.style.overflow).toBe("");
    expect(document.documentElement.classList.contains("has-expanded-card")).toBe(false);
  });

  it("collapses on window Escape", () => {
    const { node, result } = mountCard();
    act(() => result.current.toggle());
    expect(node.classList.contains("is-card-expanded")).toBe(true);
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(node.classList.contains("is-card-expanded")).toBe(false);
    expect(result.current.isFullscreen).toBe(false);
  });

  it("restores focus to the opener on collapse", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    const { node, result } = mountCard();
    opener.focus();
    expect(document.activeElement).toBe(opener);

    act(() => result.current.toggle());
    // Move focus somewhere inside the expanded card, then collapse.
    const inner = document.createElement("button");
    node.appendChild(inner);
    inner.focus();
    expect(document.activeElement).toBe(inner);

    act(() => result.current.toggle());
    expect(document.activeElement).toBe(opener);
  });

  it("keeps at most one expanded card — a second collapses the first (singleton)", () => {
    const a = mountCard("A");
    const b = mountCard("B");
    act(() => a.result.current.toggle());
    expect(a.node.classList.contains("is-card-expanded")).toBe(true);

    act(() => b.result.current.toggle());
    expect(a.node.classList.contains("is-card-expanded")).toBe(false);
    expect(a.result.current.isFullscreen).toBe(false);
    expect(b.node.classList.contains("is-card-expanded")).toBe(true);
    expect(b.result.current.isFullscreen).toBe(true);
  });

  it("closeExpandedCard() collapses the active card (safe no-op when none)", () => {
    expect(() => closeExpandedCard()).not.toThrow();
    const { node, result } = mountCard();
    act(() => result.current.toggle());
    expect(node.classList.contains("is-card-expanded")).toBe(true);
    act(() => closeExpandedCard());
    expect(node.classList.contains("is-card-expanded")).toBe(false);
    expect(document.documentElement.classList.contains("has-expanded-card")).toBe(false);
  });

  it("falls back to expanded-card mode when native requestFullscreen rejects", async () => {
    const original = Object.getOwnPropertyDescriptor(document, "fullscreenEnabled");
    Object.defineProperty(document, "fullscreenEnabled", { value: true, configurable: true });
    try {
      const node = document.createElement("div");
      node.className = "fullscreen-surface";
      document.body.appendChild(node);
      node.requestFullscreen = () => Promise.reject(new Error("denied"));
      const ref: RefObject<HTMLDivElement> = { current: node };
      const { result } = renderHook(() => useFullscreen(ref, { surface: "contribution waterfall" }));
      expect(result.current.supported).toBe(true);

      await act(async () => {
        result.current.toggle();
        await Promise.resolve();
      });

      expect(node.classList.contains("is-card-expanded")).toBe(true);
      expect(result.current.isFullscreen).toBe(true);
    } finally {
      if (original) {
        Object.defineProperty(document, "fullscreenEnabled", original);
      } else {
        delete (document as { fullscreenEnabled?: boolean }).fullscreenEnabled;
      }
    }
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
