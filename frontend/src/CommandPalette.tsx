import { useEffect, useMemo, useRef, useState } from "react";
import { Command } from "lucide-react";
import { useFocusTrap } from "./useFocusTrap";

export interface CommandAction {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  actions: CommandAction[];
}

/**
 * ⌘K accelerator. Every action it exposes ALSO has a visible control elsewhere in
 * the UI — the palette never owns a workflow, it only speeds it up. Plain
 * substring filter, no dependency. Esc/scroll-lock come from the parent useOverlay.
 */
export function CommandPalette({ isOpen, onClose, actions }: CommandPaletteProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const openerRef = useRef<Element | null>(null);
  const panelRef = useRef<HTMLElement>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  useFocusTrap(panelRef, isOpen);

  useEffect(() => {
    if (!isOpen) return;
    openerRef.current = document.activeElement;
    setQuery("");
    setActive(0);
    requestAnimationFrame(() => inputRef.current?.focus());
    return () => {
      const opener = openerRef.current;
      if (opener instanceof HTMLElement) opener.focus();
      openerRef.current = null;
    };
  }, [isOpen]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return actions;
    return actions.filter((a) => a.label.toLowerCase().includes(q));
  }, [actions, query]);

  useEffect(() => {
    setActive((prev) => Math.min(prev, Math.max(0, filtered.length - 1)));
  }, [filtered.length]);

  if (!isOpen) return null;

  const choose = (action: CommandAction | undefined) => {
    if (!action) return;
    onClose();
    action.run();
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => Math.min(i + 1, filtered.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(filtered[active]);
    }
  };

  return (
    <div className="drawer-backdrop command-backdrop" onClick={onClose} role="presentation">
      <section
        ref={panelRef}
        className="command-palette"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        <div className="command-input-row">
          <Command size={16} aria-hidden="true" />
          <input
            ref={inputRef}
            className="command-input"
            placeholder="Type a command…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            aria-label="Command search"
          />
        </div>
        <ul className="command-list" role="listbox" aria-label="Commands">
          {filtered.length === 0 ? (
            <li className="command-empty">No matching commands</li>
          ) : (
            filtered.map((action, index) => (
              <li key={action.id}>
                <button
                  type="button"
                  className={`command-item${index === active ? " active" : ""}`}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(action)}
                  role="option"
                  aria-selected={index === active}
                >
                  <span>{action.label}</span>
                  {action.hint ? <span className="command-hint">{action.hint}</span> : null}
                </button>
              </li>
            ))
          )}
        </ul>
      </section>
    </div>
  );
}
