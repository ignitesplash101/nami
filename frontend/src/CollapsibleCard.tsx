import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";
import { useRef, useState } from "react";
import { FullscreenButton } from "./FullscreenButton";
import { useFullscreen } from "./useFullscreen";

/** Drill-layer section card with an information-bearing summary while collapsed.
 *
 * Tier default is decided ONCE at mount (desktop ≥1080px opens, compact
 * collapses) and the user's toggle owns it afterwards — no flip on resize.
 * The body stays mounted (hidden) so child state (sorts, fetched metadata)
 * survives toggling. No height animation: instant toggle, reduced-motion-safe
 * by construction.
 */
export function CollapsibleCard({
  eyebrow,
  title,
  summary,
  action,
  className = "",
  defaultOpen,
  fullscreenable = false,
  surface,
  children
}: {
  eyebrow?: string;
  title: string;
  summary?: ReactNode;
  action?: ReactNode;
  className?: string;
  // Overrides the tier default (e.g. experimental sections collapse everywhere).
  defaultOpen?: boolean;
  // Opts into the shared fullscreen affordance (native + expanded-card
  // fallback). `surface` names what expands and is REQUIRED whenever this is
  // true — it labels the button and the fallback modal's aria-label.
  fullscreenable?: boolean;
  surface?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState<boolean>(() => {
    if (defaultOpen !== undefined) return defaultOpen;
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return true;
    return !window.matchMedia("(max-width: 1079.98px)").matches;
  });
  // Called unconditionally (stable hook order) regardless of `fullscreenable`
  // — a prop must never gate whether a hook runs.
  const ref = useRef<HTMLElement>(null);
  const surfaceName = surface ?? title;
  const fs = useFullscreen(ref, { surface: surfaceName });

  function handleHeadClick() {
    // Anti-trap: while expanded, this button IS the exit control (an iPhone
    // user has no hardware Esc). Collapsing the body here would unmount it
    // out from under them, so exit fullscreen first instead of toggling
    // `open` — a second click, once collapsed back to inline, behaves
    // normally.
    if (fullscreenable && fs.isFullscreen) {
      fs.toggle();
      return;
    }
    setOpen((prev) => !prev);
  }

  // The action cluster (and the fullscreen button inside it) must stay
  // mounted for the entire expanded lifetime, independent of `open` — see
  // handleHeadClick above.
  const showActions = (open && Boolean(action)) || (fullscreenable && (open || fs.isFullscreen));

  return (
    <section
      ref={ref}
      className={`result-card collapsible-card${fullscreenable ? " fullscreen-surface" : ""} ${className}`.trim()}
    >
      <div className="collapsible-head-row">
        <h3 className="collapsible-h">
          <button
            type="button"
            className="collapsible-head"
            aria-expanded={open}
            onClick={handleHeadClick}
          >
            <ChevronDown
              size={16}
              aria-hidden="true"
              className={`collapsible-chevron${open ? " open" : ""}`}
            />
            <span className="collapsible-titles">
              {eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}
              <span className="collapsible-title">{title}</span>
            </span>
            {!open && summary ? <span className="collapsible-summary">{summary}</span> : null}
          </button>
        </h3>
        {showActions ? (
          <div className="collapsible-action">
            {open && action ? action : null}
            {fullscreenable ? <FullscreenButton controller={fs} surface={surfaceName} /> : null}
          </div>
        ) : null}
      </div>
      <div className="collapsible-body" hidden={!open}>
        {children}
      </div>
    </section>
  );
}
