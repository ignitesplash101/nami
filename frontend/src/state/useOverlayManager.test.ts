import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { RefObject } from "react";
import { useOverlayManager } from "./useOverlayManager";
import { closeExpandedCard, useFullscreen } from "../useFullscreen";

/** Expand a real chart card through the fallback path so the module-level
 * singleton is genuinely occupied — the openers must collapse it. */
function expandCard() {
  const node = document.createElement("div");
  node.className = "fullscreen-surface";
  document.body.appendChild(node);
  const ref: RefObject<HTMLDivElement> = { current: node };
  const card = renderHook(() => useFullscreen(ref, { surface: "contribution waterfall" }));
  act(() => card.result.current.toggle());
  return { node, card };
}

describe("useOverlayManager", () => {
  afterEach(() => {
    act(() => closeExpandedCard());
    document.body.innerHTML = "";
    document.body.style.overflow = "";
    document.documentElement.classList.remove("has-expanded-card");
  });

  it("exposes openCommandPalette, which opens the palette", () => {
    const { result } = renderHook(() => useOverlayManager());
    expect(typeof result.current.openCommandPalette).toBe("function");
    expect(result.current.commandPalette.isOpen).toBe(false);
    act(() => result.current.openCommandPalette());
    expect(result.current.commandPalette.isOpen).toBe(true);
  });

  it("owns Save and keeps it mutually exclusive with Purge", () => {
    const { result } = renderHook(() => useOverlayManager());

    act(() => result.current.openSaveDialog());
    expect(result.current.saveDialog.isOpen).toBe(true);

    act(() => result.current.requestPurge());
    expect(result.current.saveDialog.isOpen).toBe(false);
    expect(result.current.purgeConfirm.isOpen).toBe(true);
  });

  it("keeps saved-delete and the command palette mutually exclusive with one scroll lock", () => {
    const { result } = renderHook(() => useOverlayManager());

    act(() => result.current.openSavedDeleteConfirm());
    expect(result.current.savedDeleteConfirm.isOpen).toBe(true);
    expect(result.current.commandPalette.isOpen).toBe(false);
    expect(document.body.style.overflow).toBe("hidden");

    act(() => result.current.openCommandPalette());
    expect(result.current.savedDeleteConfirm.isOpen).toBe(false);
    expect(result.current.commandPalette.isOpen).toBe(true);
    expect(document.body.style.overflow).toBe("hidden");

    act(() => result.current.openSavedDeleteConfirm());
    expect(result.current.commandPalette.isOpen).toBe(false);
    expect(result.current.savedDeleteConfirm.isOpen).toBe(true);
    expect(document.body.style.overflow).toBe("hidden");

    act(() => result.current.savedDeleteConfirm.close());
    expect(document.body.style.overflow).toBe("");
  });

  it.each([
    ["openMethodology", "methodologyDrawer"],
    ["openRailDrawer", "railDrawer"],
    ["openOpsDrawer", "opsDrawer"],
    ["openCommandPalette", "commandPalette"],
    ["openSaveDialog", "saveDialog"],
    ["openSavedDeleteConfirm", "savedDeleteConfirm"]
  ] as const)("%s closes an already-open purge confirmation", (opener, target) => {
    const { result } = renderHook(() => useOverlayManager());
    act(() => result.current.requestPurge());
    expect(result.current.purgeConfirm.isOpen).toBe(true);

    act(() => {
      if (opener === "openMethodology") result.current.openMethodology();
      else result.current[opener]();
    });

    expect(result.current.purgeConfirm.isOpen).toBe(false);
    expect(result.current[target].isOpen).toBe(true);
  });

  it("openCommandPalette collapses an expanded card (mutual exclusion)", () => {
    const { node } = expandCard();
    expect(node.classList.contains("is-card-expanded")).toBe(true);

    const { result } = renderHook(() => useOverlayManager());
    act(() => result.current.openCommandPalette());

    expect(node.classList.contains("is-card-expanded")).toBe(false);
    expect(document.documentElement.classList.contains("has-expanded-card")).toBe(false);
  });

  it.each([
    "openMethodology",
    "openRailDrawer",
    "openOpsDrawer",
    "openSaveDialog",
    "openSavedDeleteConfirm",
    "requestPurge"
  ] as const)(
    "%s collapses an expanded card (mutual exclusion)",
    (opener) => {
      const { node } = expandCard();
      expect(node.classList.contains("is-card-expanded")).toBe(true);

      const { result } = renderHook(() => useOverlayManager());
      act(() => {
        (result.current[opener] as () => void)();
      });

      expect(node.classList.contains("is-card-expanded")).toBe(false);
    }
  );

  it("⌘K collapses an expanded card and opens the palette", () => {
    const { node } = expandCard();
    const { result } = renderHook(() => useOverlayManager());
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }));
    });
    expect(node.classList.contains("is-card-expanded")).toBe(false);
    expect(result.current.commandPalette.isOpen).toBe(true);
  });
});
