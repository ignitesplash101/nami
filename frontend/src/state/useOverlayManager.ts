import { useEffect, useState } from "react";
import { useMethodologyDrawer } from "../useMethodologyDrawer";
import { useOverlay } from "../useOverlay";

/** Owns every overlay plus their mutual exclusion: two useOverlay overlays
 * must never be open at once (both Esc listeners sit on window and would
 * close together), so each opener closes the others first. */
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
    railDrawer.close();
    commandPalette.close();
    opsDrawer.close();
    methodologyDrawer.open(section);
  }

  function openRailDrawer() {
    methodologyDrawer.close();
    commandPalette.close();
    opsDrawer.close();
    railDrawer.open();
  }

  function openOpsDrawer() {
    methodologyDrawer.close();
    railDrawer.close();
    commandPalette.close();
    opsDrawer.open();
  }

  // Purge flow: the ops drawer CLOSES before the confirm dialog opens — two
  // useOverlay overlays must never be open at once (window-level Esc would
  // close both together).
  function requestPurge() {
    opsDrawer.close();
    purgeConfirm.open();
  }

  // ⌘K / Ctrl+K opens the command palette (accelerator only — every command it
  // exposes also has a visible control elsewhere). open/close are stable.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        methodologyDrawer.close();
        railDrawer.close();
        opsDrawer.close();
        commandPalette.open();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [commandPalette.open, methodologyDrawer.close, opsDrawer.close, railDrawer.close]);

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
    requestPurge
  };
}
