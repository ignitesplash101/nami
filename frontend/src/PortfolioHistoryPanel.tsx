import { useEffect, useState } from "react";
import { Archive, Plus } from "lucide-react";
import {
  createPortfolio,
  createPortfolioSnapshot,
  listPortfolioSnapshots,
  listSavedPortfolios,
  toApiError
} from "./api";
import type { ApiError } from "./api";
import { ErrorNotice } from "./ErrorNotice";
import { useToasts } from "./toast";
import type { PortfolioSnapshotRecord, SavedPortfolioRecord } from "./types";

interface PortfolioHistoryPanelProps {
  // Holdings currently in the active custom-portfolio editor; the "Save
  // current as snapshot" action stamps these as a dated snapshot.
  currentHoldings: Record<string, number>;
  // When set, snapshotting is disabled (e.g. the editor is in Shares/MTM mode and
  // snapshots store weights in v1). The string is shown as the reason.
  snapshotDisabledReason?: string;
  onLoadSnapshot: (snapshot: PortfolioSnapshotRecord) => void;
  onForbidden?: () => void;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function PortfolioHistoryPanel({
  currentHoldings,
  snapshotDisabledReason,
  onLoadSnapshot,
  onForbidden
}: PortfolioHistoryPanelProps) {
  const [portfolios, setPortfolios] = useState<SavedPortfolioRecord[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [snapshots, setSnapshots] = useState<PortfolioSnapshotRecord[]>([]);
  const [newName, setNewName] = useState("");
  const [snapDate, setSnapDate] = useState(todayIso());
  const [snapNotes, setSnapNotes] = useState("");
  const [error, setError] = useState<ApiError | string | null>(null);
  const [loading, setLoading] = useState(false);
  const { push } = useToasts();

  function reportError(exc: unknown) {
    const err = toApiError(exc);
    if (err.kind === "forbidden") onForbidden?.();
    setError(err);
  }

  useEffect(() => {
    setLoading(true);
    listSavedPortfolios()
      .then(setPortfolios)
      .catch((exc) => reportError(exc))
      .finally(() => setLoading(false));
    // Mount-only fetch; a remount (key change) refetches.
  }, []);

  useEffect(() => {
    if (!activeId) {
      setSnapshots([]);
      return;
    }
    listPortfolioSnapshots(activeId)
      .then(setSnapshots)
      .catch((exc) => reportError(exc));
  }, [activeId]);

  async function handleCreate() {
    if (!newName.trim()) return;
    try {
      const rec = await createPortfolio({
        name: newName.trim(),
        description: "",
        owner_label: null
      });
      setPortfolios((p) => [rec, ...p]);
      setNewName("");
      setActiveId(rec.id);
      push({ variant: "success", message: "Portfolio created." });
    } catch (exc) {
      reportError(exc);
    }
  }

  async function handleSnapshot() {
    if (snapshotDisabledReason) {
      setError(snapshotDisabledReason);
      return;
    }
    if (!activeId) {
      setError("Select a saved portfolio first.");
      return;
    }
    if (Object.keys(currentHoldings).length === 0) {
      setError("Active portfolio editor is empty; nothing to snapshot.");
      return;
    }
    try {
      const snap = await createPortfolioSnapshot(activeId, {
        as_of_date: snapDate,
        holdings: currentHoldings,
        notes: snapNotes,
        owner_label: null
      });
      setSnapshots((s) => [snap, ...s]);
      setSnapNotes("");
      push({ variant: "success", message: "Snapshot saved." });
    } catch (exc) {
      reportError(exc);
    }
  }

  return (
    <section className="result-card portfolio-history">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Library</p>
          <h3>Saved portfolios &amp; snapshots</h3>
        </div>
        <Archive size={18} />
      </div>

      <div className="port-history-create">
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="New portfolio name (e.g. 'Active book')"
          aria-label="New portfolio name"
          maxLength={200}
        />
        <button className="ghost-button" onClick={handleCreate} disabled={!newName.trim()}>
          <Plus size={13} /> Create
        </button>
      </div>

      {error ? <ErrorNotice variant="inline" error={error} /> : null}
      {loading ? <p className="muted">Loading...</p> : null}

      {portfolios.length === 0 ? (
        <p className="muted">
          No saved portfolios yet. Create one above to start snapshotting your book
          over time.
        </p>
      ) : (
        <>
          <label>
            Portfolio
            <select
              value={activeId ?? ""}
              onChange={(e) => setActiveId(e.target.value || null)}
            >
              <option value="">(select)</option>
              {portfolios.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>

          {activeId ? (
            <>
              <div className="snap-create">
                <label>
                  As-of date
                  <input
                    type="date"
                    max={todayIso()}
                    value={snapDate}
                    onChange={(e) => setSnapDate(e.target.value)}
                  />
                </label>
                <label>
                  Notes
                  <input
                    value={snapNotes}
                    onChange={(e) => setSnapNotes(e.target.value)}
                    placeholder="Pre-rebalance, etc."
                  />
                </label>
                <button
                  className="primary-button"
                  onClick={handleSnapshot}
                  disabled={Boolean(snapshotDisabledReason)}
                  title={snapshotDisabledReason}
                >
                  Save current holdings as snapshot
                </button>
                {snapshotDisabledReason ? (
                  <p className="muted" style={{ gridColumn: "1 / -1", margin: 0 }}>
                    {snapshotDisabledReason}
                  </p>
                ) : null}
              </div>

              <div className="snap-list">
                <h4>Snapshots</h4>
                {snapshots.length === 0 ? (
                  <p className="muted">No snapshots yet for this portfolio.</p>
                ) : (
                  <ol>
                    {snapshots.map((snap) => (
                      <li key={snap.id}>
                        <div className="snap-row">
                          <span className="snap-date">
                            <code>{snap.as_of_date}</code>
                          </span>
                          <span className="muted">
                            {Object.keys(snap.holdings).length} positions
                          </span>
                          <button
                            className="ghost-button"
                            onClick={() => onLoadSnapshot(snap)}
                          >
                            Load
                          </button>
                        </div>
                        {snap.notes ? (
                          <p className="snap-notes muted">{snap.notes}</p>
                        ) : null}
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            </>
          ) : null}
        </>
      )}
    </section>
  );
}
