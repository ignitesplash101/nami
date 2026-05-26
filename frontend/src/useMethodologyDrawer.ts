import { useCallback, useState } from "react";
import { useOverlay } from "./useOverlay";

export interface MethodologyDrawerState {
  isOpen: boolean;
  initialSection: string | null;
  open: (section?: string) => void;
  close: () => void;
}

export function useMethodologyDrawer(): MethodologyDrawerState {
  const [initialSection, setInitialSection] = useState<string | null>(null);
  const overlay = useOverlay({ onClose: () => setInitialSection(null) });

  const open = useCallback(
    (section?: string) => {
      setInitialSection(section ?? null);
      overlay.open();
    },
    [overlay]
  );

  return {
    isOpen: overlay.isOpen,
    initialSection,
    open,
    close: overlay.close,
  };
}
