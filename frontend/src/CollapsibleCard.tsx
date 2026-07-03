import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";

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
  children
}: {
  eyebrow?: string;
  title: string;
  summary?: ReactNode;
  action?: ReactNode;
  className?: string;
  // Overrides the tier default (e.g. experimental sections collapse everywhere).
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState<boolean>(() => {
    if (defaultOpen !== undefined) return defaultOpen;
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return true;
    return !window.matchMedia("(max-width: 1079.98px)").matches;
  });
  return (
    <section className={`result-card collapsible-card ${className}`.trim()}>
      <div className="collapsible-head-row">
        <h3 className="collapsible-h">
          <button
            type="button"
            className="collapsible-head"
            aria-expanded={open}
            onClick={() => setOpen((prev) => !prev)}
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
        {open && action ? <div className="collapsible-action">{action}</div> : null}
      </div>
      <div className="collapsible-body" hidden={!open}>
        {children}
      </div>
    </section>
  );
}
