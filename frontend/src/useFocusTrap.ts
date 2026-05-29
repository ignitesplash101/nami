import { useEffect } from "react";
import type { RefObject } from "react";

const FOCUSABLE_SELECTOR =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),' +
  'textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/**
 * Contain Tab focus within `ref` while `active`. Wraps from the last focusable
 * element back to the first (and vice-versa with Shift+Tab), and pulls focus
 * back in if it has somehow escaped the dialog.
 *
 * This complements — does NOT duplicate — the parent overlay's body-scroll-lock
 * and Esc handling (useOverlay) and the dialog's own initial-focus / focus-return
 * effects. It adds ONLY the Tab-cycling containment those don't provide.
 */
export function useFocusTrap(ref: RefObject<HTMLElement | null>, active: boolean): void {
  useEffect(() => {
    if (!active) return;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const node = ref.current;
      if (!node) return;

      const focusable = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeEl = document.activeElement;

      if (event.shiftKey) {
        if (activeEl === first || !node.contains(activeEl)) {
          event.preventDefault();
          last.focus();
        }
      } else if (activeEl === last || !node.contains(activeEl)) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [ref, active]);
}
