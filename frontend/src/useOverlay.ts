import { useCallback, useEffect, useState } from "react";

export interface OverlayOptions {
  /**
   * Called BEFORE isOpen flips to false. Lets the consumer clear state
   * (e.g. initialSection on the methodology drawer) consistently for both
   * the explicit close() call and the Esc-key path.
   */
  onClose?: () => void;
}

export interface OverlayState {
  isOpen: boolean;
  open: () => void;
  close: () => void;
}

/**
 * Shared overlay state for modal/drawer components. Adds body scroll lock and
 * Esc-to-close while the overlay is open. The onClose callback fires before
 * the overlay flips closed, so consumer-specific cleanup runs deterministically.
 */
export function useOverlay(options?: OverlayOptions): OverlayState {
  const [isOpen, setIsOpen] = useState(false);

  const open = useCallback(() => {
    setIsOpen(true);
  }, []);

  const close = useCallback(() => {
    options?.onClose?.();
    setIsOpen(false);
  }, [options]);

  useEffect(() => {
    if (!isOpen) return;

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        options?.onClose?.();
        setIsOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);

    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen, options]);

  return { isOpen, open, close };
}
