import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { saveScenario } from "./api";
import type {
  AnalogEvent,
  SavedScenarioRecord,
  ScenarioReproducibility,
  ScenarioResult
} from "./types";

const OWNER_LABEL_KEY = "nami_owner_label";

interface SaveScenarioDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSaved: (record: SavedScenarioRecord) => void;
  result: ScenarioResult;
  analogEvents: Record<string, AnalogEvent>;
  reproducibility: ScenarioReproducibility;
}

export function SaveScenarioDialog({
  isOpen,
  onClose,
  onSaved,
  result,
  analogEvents,
  reproducibility
}: SaveScenarioDialogProps) {
  const [name, setName] = useState("");
  const [tagsInput, setTagsInput] = useState("");
  const [notes, setNotes] = useState("");
  const [ownerLabel, setOwnerLabel] = useState(
    () => window.localStorage.getItem(OWNER_LABEL_KEY) ?? ""
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    requestAnimationFrame(() => nameRef.current?.focus());

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  async function handleSave() {
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    setError(null);
    setSaving(true);
    window.localStorage.setItem(OWNER_LABEL_KEY, ownerLabel);
    try {
      const tags = tagsInput
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const rec = await saveScenario({
        name: name.trim(),
        tags,
        notes,
        owner_label: ownerLabel || null,
        result,
        analog_events_snapshot: analogEvents,
        reproducibility,
        portfolio_snapshot_ref: null
      });
      onSaved(rec);
      setName("");
      setTagsInput("");
      setNotes("");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="drawer-backdrop" onClick={onClose} role="presentation">
      <aside
        className="save-dialog"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Save scenario"
      >
        <header className="drawer-header">
          <h2>Save scenario</h2>
          <button className="drawer-close" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>
        <div className="save-dialog-body">
          <label>
            Name
            <input
              ref={nameRef}
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
              placeholder="e.g. Q2 backdated trade-war replay"
            />
          </label>
          <label>
            Tags (comma-separated)
            <input
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              placeholder="geopolitical, backdated, sign-off"
            />
          </label>
          <label>
            Notes
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Why this scenario matters, sign-off context, etc."
            />
          </label>
          <label>
            Owner initials (optional — saved to your browser)
            <input
              value={ownerLabel}
              onChange={(e) => setOwnerLabel(e.target.value)}
              maxLength={32}
              placeholder="rs"
            />
          </label>
          <div className="save-dialog-meta muted">
            <span>
              Portfolio: <strong>{result.portfolio_name}</strong>
            </span>
            <span>
              As-of (effective): <code>{result.market_date}</code>
            </span>
            <span>
              Narrative mode: <code>{result.narrative_mode}</code>
            </span>
            <span>Total P&amp;L: {(result.portfolio_pnl.total_pnl * 100).toFixed(2)}%</span>
          </div>
          {error ? <div className="inline-error">{error}</div> : null}
          <div className="button-row">
            <button className="primary-button" onClick={handleSave} disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </button>
            <button className="ghost-button" onClick={onClose} disabled={saving}>
              Cancel
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
}
