import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Info } from "lucide-react";

/** Tap-friendly explainer: a small ⓘ button toggling an anchored popover.
 * Replaces hover-only title= attributes, which are unreachable on touch.
 * Deliberately NOT a useOverlay consumer — no body scroll lock, and its
 * listeners attach only while open without stopping propagation (an InfoTip
 * closing alongside a drawer on one Esc press is acceptable by design). */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <span className="infotip" ref={rootRef}>
      <button
        type="button"
        className="infotip-btn"
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        <Info size={13} aria-hidden="true" />
      </button>
      {open ? (
        <span className="infotip-pop" role="note">
          {children}
        </span>
      ) : null}
    </span>
  );
}
