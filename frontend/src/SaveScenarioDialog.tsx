import { useEffect, useRef, useState } from "react";
import { saveScenario, toApiError } from "./api";
import type { ApiError } from "./api";
import { formatCurrency, formatPercent } from "./charts";
import { ErrorNotice } from "./ErrorNotice";
import { OverlayShell } from "./OverlayShell";
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
  onForbidden?: () => void;
  result: ScenarioResult;
  analogEvents: Record<string, AnalogEvent>;
  reproducibility: ScenarioReproducibility;
}

export function SaveScenarioDialog({
  isOpen,
  onClose,
  onSaved,
  onForbidden,
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
  const [error, setError] = useState<ApiError | string | null>(null);
  const [saving, setSaving] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  // Dialog-specific focus management ONLY: body scroll lock + Escape are
  // owned by the parent's useOverlay() (App.tsx::saveDialog). OverlayShell
  // owns focus trapping, focus return, backdrop click, and initial focus.
  useEffect(() => {
    if (!isOpen) return;
    setError(null);
  }, [isOpen]);

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
      const err = toApiError(exc);
      if (err.kind === "forbidden") onForbidden?.();
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <OverlayShell
      isOpen={isOpen}
      onClose={onClose}
      className="save-dialog"
      ariaLabel="Save scenario"
      title="Save scenario"
      initialFocusRef={nameRef}
    >
      <div className="save-dialog-body">
        <label>
          Name
          <input
            ref={nameRef}
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={200}
            placeholder="e.g. Q2 backdated trade-war replay"
            aria-invalid={Boolean(error)}
            aria-describedby={error ? "save-dialog-error" : undefined}
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
            <span>Total P&amp;L: {formatPercent(result.portfolio_pnl.total_pnl, 2)}</span>
            {result.portfolio_nav != null ? (
              <span>
                NAV:{" "}
                <code>
                  {formatCurrency(result.portfolio_nav, result.reporting_currency ?? "USD")}
                </code>
              </span>
            ) : null}
        </div>
        {error ? <ErrorNotice variant="inline" error={error} id="save-dialog-error" /> : null}
        <div className="button-row">
          <button className="primary-button" onClick={handleSave} disabled={saving}>
            {saving ? "Saving..." : "Save"}
          </button>
          <button className="ghost-button" onClick={onClose} disabled={saving}>
            Cancel
          </button>
        </div>
      </div>
    </OverlayShell>
  );
}
