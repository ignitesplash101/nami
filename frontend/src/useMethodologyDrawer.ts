import { useCallback, useEffect, useState } from "react";

export interface MethodologyDrawerState {
  isOpen: boolean;
  initialSection: string | null;
  open: (section?: string) => void;
  close: () => void;
}

export function useMethodologyDrawer(): MethodologyDrawerState {
  const [isOpen, setIsOpen] = useState(false);
  const [initialSection, setInitialSection] = useState<string | null>(null);

  const open = useCallback((section?: string) => {
    setInitialSection(section ?? null);
    setIsOpen(true);
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
    setInitialSection(null);
  }, []);

  useEffect(() => {
    if (!isOpen) return;

    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setIsOpen(false);
        setInitialSection(null);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen]);

  return { isOpen, initialSection, open, close };
}
