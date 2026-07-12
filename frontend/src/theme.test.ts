import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readTheme, useTheme } from "./theme";
import { chartTheme, resetChartThemeForTests } from "./charts";

function stubMatchMedia(matches: boolean): Array<(event: MediaQueryListEvent) => void> {
  const listeners: Array<(event: MediaQueryListEvent) => void> = [];
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      addEventListener: (_type: string, cb: (event: MediaQueryListEvent) => void) => {
        listeners.push(cb);
      },
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      onchange: null,
      dispatchEvent: () => false
    }))
  );
  return listeners;
}

function themeColorMeta(): HTMLMetaElement {
  let meta = document.querySelector('meta[name="theme-color"]') as HTMLMetaElement | null;
  if (!meta) {
    meta = document.createElement("meta");
    meta.setAttribute("name", "theme-color");
    document.head.appendChild(meta);
  }
  return meta;
}

describe("theme", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.dataset.theme = "dark";
    themeColorMeta().setAttribute("content", "#0b1b2b");
    resetChartThemeForTests();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.documentElement.style.removeProperty("--up");
    document.documentElement.dataset.theme = "dark";
    resetChartThemeForTests();
  });

  it("readTheme mirrors the data-theme attribute", () => {
    expect(readTheme()).toBe("dark");
    document.documentElement.dataset.theme = "light";
    expect(readTheme()).toBe("light");
  });

  it("toggleTheme flips data-theme, persists the choice, and updates theme-color", () => {
    stubMatchMedia(false);
    const { result } = renderHook(() => useTheme());

    act(() => result.current.toggleTheme());
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("nami-theme")).toBe("light");
    expect(themeColorMeta().getAttribute("content")).toBe("#f4efe3");

    act(() => result.current.toggleTheme());
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("nami-theme")).toBe("dark");
    expect(themeColorMeta().getAttribute("content")).toBe("#0b1b2b");
  });

  it("follows OS scheme changes only until the user chooses explicitly", () => {
    const listeners = stubMatchMedia(false);
    const { result } = renderHook(() => useTheme());

    act(() => {
      listeners.forEach((cb) => cb({ matches: true } as MediaQueryListEvent));
    });
    expect(document.documentElement.dataset.theme).toBe("light");

    act(() => result.current.toggleTheme());
    expect(localStorage.getItem("nami-theme")).toBe("dark");

    act(() => {
      listeners.forEach((cb) => cb({ matches: true } as MediaQueryListEvent));
    });
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("chartTheme re-reads tokens after a theme flip (cache keyed by data-theme)", () => {
    document.documentElement.style.setProperty("--up", "#111111");
    expect(chartTheme().up).toBe("#111111");

    document.documentElement.style.setProperty("--up", "#222222");
    expect(chartTheme().up).toBe("#111111");

    document.documentElement.dataset.theme = "light";
    expect(chartTheme().up).toBe("#222222");
  });
});
