import { useRef } from "react";
import type { ReactNode } from "react";
import { useScrollFade } from "./useScrollFade";

export interface TabItem<K extends string> {
  key: K;
  label: ReactNode;
  content: ReactNode;
  /** Shows a small pulsing dot after the label (e.g. a run streaming while
   * the user is parked on another area). Purely decorative — the dot is
   * aria-hidden and never joins the accessible name; the app's single
   * polite live region already carries run lifecycle to screen readers. */
  busy?: boolean;
}

/** Accessible tablist with mounted-but-hidden panels (the CollapsibleCard
 * trick: child state — sorts, fetched data, chart instances — survives tab
 * switches, and the one-shot nami-rise stagger never replays because nothing
 * remounts). Automatic activation: Arrow keys move AND select, matching the
 * app's radiogroup controls. A switch dispatches a window resize on the next
 * frame so Plotly (responsive: true) corrects any drift that accumulated
 * while its panel was hidden. */
export function Tabs<K extends string>({
  items,
  active,
  onChange,
  ariaLabel,
  idBase,
  className
}: {
  items: TabItem<K>[];
  active: K;
  onChange: (key: K) => void;
  ariaLabel: string;
  idBase: string;
  className?: string;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  const hasOverflow = useScrollFade(listRef);

  function select(key: K) {
    if (key === active) return;
    onChange(key);
    requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
  }

  function move(direction: 1 | -1) {
    const index = items.findIndex((item) => item.key === active);
    const next = items[(index + direction + items.length) % items.length];
    select(next.key);
  }

  return (
    <div className={`tabs${className ? ` ${className}` : ""}`}>
      <div className={`tablist-wrap${hasOverflow ? " has-overflow" : ""}`}>
        <div
          ref={listRef}
          role="tablist"
          aria-label={ariaLabel}
          className="tablist"
          onKeyDown={(event) => {
            if (event.key === "ArrowRight" || event.key === "ArrowDown") {
              event.preventDefault();
              move(1);
            } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
              event.preventDefault();
              move(-1);
            } else if (event.key === "Home") {
              event.preventDefault();
              select(items[0].key);
            } else if (event.key === "End") {
              event.preventDefault();
              select(items[items.length - 1].key);
            }
          }}
        >
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              id={`${idBase}-tab-${item.key}`}
              aria-selected={active === item.key}
              aria-controls={`${idBase}-panel-${item.key}`}
              tabIndex={active === item.key ? 0 : -1}
              className={active === item.key ? "active" : ""}
              onClick={() => select(item.key)}
            >
              {item.label}
              {item.busy ? <span className="tab-busy-dot" aria-hidden="true" /> : null}
            </button>
          ))}
        </div>
      </div>
      {items.map((item) => (
        <div
          key={item.key}
          role="tabpanel"
          id={`${idBase}-panel-${item.key}`}
          aria-labelledby={`${idBase}-tab-${item.key}`}
          hidden={active !== item.key}
          className="tab-panel"
        >
          {item.content}
        </div>
      ))}
    </div>
  );
}
