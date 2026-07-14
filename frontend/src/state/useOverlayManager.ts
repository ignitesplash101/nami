import { useCallback, useEffect, useState } from "react";
import { useMethodologyDrawer } from "../useMethodologyDrawer";
import { useOverlay } from "../useOverlay";
import { closeExpandedCard } from "../useFullscreen";

// Before opening any overlay, clear BOTH fullscreen presentations of a chart
// card: the app-owned expanded card (a window-Esc owner) AND a natively
// fullscreened element — a palette/drawer renders OUTSIDE the fullscreened
// subtree, so it would open invisibly (e.g. ⌘K over a fullscreen chart).
function dismissFullscreenSurfaces() {
  closeExpandedCard();
  if (typeof document !== "undefined" && document.fullscreenElement) {
    void document.exitFullscreen();
  }
}

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
  const saveDialog = useOverlay();
  const savedDeleteConfirm = useOverlay();

  const closeAdminOverlays = useCallback(() => {
    opsDrawer.close();
    purgeConfirm.close();
    saveDialog.close();
    savedDeleteConfirm.close();
  }, [opsDrawer.close, purgeConfirm.close, saveDialog.close, savedDeleteConfirm.close]);

  const closeAllOverlays = useCallback(() => {
    methodologyDrawer.close();
    railDrawer.close();
    commandPalette.close();
    closeAdminOverlays();
  }, [
    closeAdminOverlays,
    commandPalette.close,
    methodologyDrawer.close,
    railDrawer.close
  ]);

  const prepareOverlayOpen = useCallback(() => {
    dismissFullscreenSurfaces();
    closeAllOverlays();
  }, [closeAllOverlays]);

  function openMethodology(section?: string) {
    prepareOverlayOpen();
    methodologyDrawer.open(section);
  }

  function openRailDrawer() {
    prepareOverlayOpen();
    railDrawer.open();
  }

  function openOpsDrawer() {
    prepareOverlayOpen();
    opsDrawer.open();
  }

  // ⌘K entry and the visible topbar button share this ONE opener — direct
  // commandPalette.open calls are forbidden (they'd skip dismissFullscreenSurfaces).
  // Deps are all stable (useOverlay open/close), so the ⌘K effect below stays
  // registered once.
  const openCommandPalette = useCallback(() => {
    prepareOverlayOpen();
    commandPalette.open();
  }, [commandPalette.open, prepareOverlayOpen]);

  function openSaveDialog() {
    prepareOverlayOpen();
    saveDialog.open();
  }

  function openSavedDeleteConfirm() {
    prepareOverlayOpen();
    savedDeleteConfirm.open();
  }

  // Purge flow: the ops drawer CLOSES before the confirm dialog opens — two
  // useOverlay overlays must never be open at once (window-level Esc would
  // close both together).
  function requestPurge() {
    prepareOverlayOpen();
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
    saveDialog,
    savedDeleteConfirm,
    openMethodology,
    openRailDrawer,
    openOpsDrawer,
    openCommandPalette,
    openSaveDialog,
    openSavedDeleteConfirm,
    requestPurge,
    closeAdminOverlays,
    closeAllOverlays
  };
}
