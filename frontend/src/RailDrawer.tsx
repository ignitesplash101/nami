import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { X } from "lucide-react";

interface RailDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  children: ReactNode;
}

export function RailDrawer({ isOpen, onClose, children }: RailDrawerProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<Element | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    openerRef.current = document.activeElement;
    requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => {
      const opener = openerRef.current;
      if (opener instanceof HTMLElement) {
        opener.focus();
      }
      openerRef.current = null;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="drawer-backdrop" onClick={onClose} role="presentation">
      <aside
        className="rail-drawer-panel"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Portfolio and access settings"
      >
        <header className="drawer-header">
          <h2>Setup</h2>
          <button
            ref={closeButtonRef}
            className="drawer-close"
            onClick={onClose}
            aria-label="Close setup panel"
          >
            <X size={18} />
          </button>
        </header>
        <div className="rail-drawer-body">{children}</div>
      </aside>
    </div>
  );
}
