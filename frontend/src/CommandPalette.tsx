import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Command } from "lucide-react";
import { OverlayShell } from "./OverlayShell";

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
  const idBase = useId();
  const listboxId = `${idBase}-command-listbox`;
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (!isOpen) return;
    setQuery("");
    setActive(0);
  }, [isOpen]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return actions;
    return actions.filter((a) => a.label.toLowerCase().includes(q));
  }, [actions, query]);

  useEffect(() => {
    setActive((prev) => Math.min(prev, Math.max(0, filtered.length - 1)));
  }, [filtered.length]);

  const choose = (action: CommandAction | undefined) => {
    if (!action) return;
    onClose();
    action.run();
  };

  const optionId = (action: CommandAction) =>
    `${idBase}-command-${encodeURIComponent(action.id)}`;

  useEffect(() => {
    const action = filtered[active];
    if (!isOpen || !action) return;
    document.getElementById(optionId(action))?.scrollIntoView?.({ block: "nearest" });
  }, [active, filtered, isOpen]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (filtered.length) setActive((i) => (i + 1) % filtered.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (filtered.length) setActive((i) => (i - 1 + filtered.length) % filtered.length);
    } else if (event.key === "Home") {
      event.preventDefault();
      if (filtered.length) setActive(0);
    } else if (event.key === "End") {
      event.preventDefault();
      if (filtered.length) setActive(filtered.length - 1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(filtered[active]);
    }
  };

  return (
    <OverlayShell
      isOpen={isOpen}
      onClose={onClose}
      className="command-palette"
      ariaLabel="Command palette"
      backdropClassName="drawer-backdrop command-backdrop"
      initialFocusRef={inputRef}
      panelElement="section"
    >
      <div className="command-input-row">
        <Command size={16} aria-hidden="true" />
        <input
          ref={inputRef}
          className="command-input"
          placeholder="Type a command…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
          role="combobox"
          aria-autocomplete="list"
          aria-haspopup="listbox"
          aria-expanded={isOpen}
          aria-controls={listboxId}
          aria-activedescendant={filtered[active] ? optionId(filtered[active]) : undefined}
          aria-label="Command search"
        />
      </div>
      <ul id={listboxId} className="command-list" role="listbox" aria-label="Commands">
        {filtered.map((action, index) => (
          <li
            key={action.id}
            id={optionId(action)}
            className={`command-item${index === active ? " active" : ""}`}
            onMouseEnter={() => setActive(index)}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => choose(action)}
            role="option"
            aria-selected={index === active}
          >
            <span>{action.label}</span>
            {action.hint ? <span className="command-hint">{action.hint}</span> : null}
          </li>
        ))}
      </ul>
      {filtered.length === 0 ? (
        <p className="command-empty" role="status" aria-live="polite">
          No matching commands
        </p>
      ) : null}
    </OverlayShell>
  );
}
