import { useCallback, useEffect, useState } from "react";
import { useMethodologyDrawer } from "../useMethodologyDrawer";
import { useOverlay } from "../useOverlay";
import { closeExpandedCard } from "../useFullscreen";

/** Owns every overlay plus their mutual exclusion: two window-level Esc owners
 * must never coexist. Both useOverlay overlays and an expanded chart card
 * (`useFullscreen`'s fallback) own a window Esc listener, so each opener closes
 * the other overlays AND collapses any expanded card first. */
export function useOverlayManager() {
  const methodologyDrawer = useMethodologyDrawer();
  // Latched on first open: the lazy chunk (react-markdown) fetches on demand,
  // then the drawer stays mounted so its accordion state survives close/reopen.
  const [methodologyMounted, setMethodologyMounted] = useState(false);
  useEffect(() => {
    if (methodologyDrawer.isOpen) setMethodologyMounted(true);
  }, [methodologyDrawer.isOpen]);
  const railDrawer = useOverlay();
  const commandPalette = useOverlay();
  const opsDrawer = useOverlay();
  const purgeConfirm = useOverlay();

  function openMethodology(section?: string) {
    closeExpandedCard();
    railDrawer.close();
    commandPalette.close();
    opsDrawer.close();
    methodologyDrawer.open(section);
  }

  function openRailDrawer() {
    closeExpandedCard();
    methodologyDrawer.close();
    commandPalette.close();
    opsDrawer.close();
    railDrawer.open();
  }

  function openOpsDrawer() {
    closeExpandedCard();
    methodologyDrawer.close();
    railDrawer.close();
    commandPalette.close();
    opsDrawer.open();
  }

  // ⌘K entry and the visible topbar button share this ONE opener — direct
  // commandPalette.open calls are forbidden (they'd skip closeExpandedCard).
  // Deps are all stable (useOverlay open/close), so the ⌘K effect below stays
  // registered once.
  const openCommandPalette = useCallback(() => {
    closeExpandedCard();
    methodologyDrawer.close();
    railDrawer.close();
    opsDrawer.close();
    commandPalette.open();
  }, [commandPalette.open, methodologyDrawer.close, opsDrawer.close, railDrawer.close]);

  // Purge flow: the ops drawer CLOSES before the confirm dialog opens — two
  // useOverlay overlays must never be open at once (window-level Esc would
  // close both together).
  function requestPurge() {
    closeExpandedCard();
    opsDrawer.close();
    purgeConfirm.open();
  }

  // ⌘K / Ctrl+K opens the command palette (accelerator only — every command it
  // exposes also has a visible control elsewhere).
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openCommandPalette();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openCommandPalette]);

  return {
    methodologyDrawer,
    methodologyMounted,
    railDrawer,
    commandPalette,
    opsDrawer,
    purgeConfirm,
    openMethodology,
    openRailDrawer,
    openOpsDrawer,
    openCommandPalette,
    requestPurge
  };
}
