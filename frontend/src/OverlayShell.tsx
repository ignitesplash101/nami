import { useEffect, useRef } from "react";
import type { MouseEvent, ReactNode, RefObject } from "react";
import { X } from "lucide-react";
import { useFocusTrap } from "./useFocusTrap";

interface OverlayShellProps {
  isOpen: boolean;
  onClose: () => void;
  className: string;
  ariaLabel: string;
  children: ReactNode;
  title?: string;
  closeLabel?: string;
  backdropClassName?: string;
  initialFocusRef?: RefObject<HTMLElement>;
  panelElement?: "aside" | "section";
}

export function OverlayShell({
  isOpen,
  onClose,
  className,
  ariaLabel,
  children,
  title,
  closeLabel = "Close",
  backdropClassName = "drawer-backdrop",
  initialFocusRef,
  panelElement = "aside"
}: OverlayShellProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<Element | null>(null);
  const panelRef = useRef<HTMLElement>(null);

  useFocusTrap(panelRef, isOpen);

  useEffect(() => {
    if (!isOpen) return;
    openerRef.current = document.activeElement;
    requestAnimationFrame(() => {
      (initialFocusRef?.current ?? closeButtonRef.current)?.focus();
    });
    return () => {
      const opener = openerRef.current;
      if (opener instanceof HTMLElement) {
        opener.focus();
      }
      openerRef.current = null;
    };
  }, [initialFocusRef, isOpen]);

  if (!isOpen) return null;

  const panelProps = {
    ref: panelRef,
    className,
    onClick: (event: MouseEvent<HTMLElement>) => event.stopPropagation(),
    role: "dialog",
    "aria-modal": true,
    "aria-label": ariaLabel
  };

  const body = (
    <>
      {title ? (
        <header className="drawer-header">
          <h2>{title}</h2>
          <button
            ref={closeButtonRef}
            className="drawer-close"
            onClick={onClose}
            aria-label={closeLabel}
          >
            <X size={18} />
          </button>
        </header>
      ) : null}
      {children}
    </>
  );

  return (
    <div className={backdropClassName} onClick={onClose} role="presentation">
      {panelElement === "section" ? (
        <section {...panelProps}>{body}</section>
      ) : (
        <aside {...panelProps}>{body}</aside>
      )}
    </div>
  );
}
