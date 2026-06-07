import type { ReactNode } from "react";
import { OverlayShell } from "./OverlayShell";

interface RailDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  children: ReactNode;
}

export function RailDrawer({ isOpen, onClose, children }: RailDrawerProps) {
  return (
    <OverlayShell
      isOpen={isOpen}
      onClose={onClose}
      className="rail-drawer-panel"
      ariaLabel="Portfolio and access settings"
      title="Setup"
      closeLabel="Close setup panel"
    >
      <div className="rail-drawer-body">{children}</div>
    </OverlayShell>
  );
}
