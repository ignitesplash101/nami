import { useEffect, useState } from "react";
import { BookMarked, Download, Trash2 } from "lucide-react";
import {
  deleteSavedScenario,
  getSavedScenario,
  listSavedScenarios,
  savedScenarioDownloadUrl,
  toApiError
} from "./api";
import type { ApiError } from "./api";
import { formatPercent } from "./charts";
import { ConfirmDialog } from "./ConfirmDialog";
import { ErrorNotice } from "./ErrorNotice";
import { relativeTime, slugify } from "./format";
import { useToasts } from "./toast";
import { useOverlay } from "./useOverlay";
import type { ScenarioRunResponse, SavedScenarioListItem } from "./types";

interface SavedScenariosPanelProps {
  reloadKey: number;  // bump to trigger refresh after a new save
  onOpen: (envelope: ScenarioRunResponse) => void;
  onForbidden?: () => void;
}

export function SavedScenariosPanel({ reloadKey, onOpen, onForbidden }: SavedScenariosPanelProps) {
  const [items, setItems] = useState<SavedScenarioListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [tagFilter, setTagFilter] = useState<string>("");
  const [error, setError] = useState<ApiError | string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<SavedScenarioListItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const confirmDelete = useOverlay();
  const { push } = useToasts();

  function reportError(exc: unknown) {
    const err = toApiError(exc);
    if (err.kind === "forbidden") onForbidden?.();
    setError(err);
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listSavedScenarios(tagFilter || undefined)
      .then((data) => {
        if (!cancelled) setItems(data);
      })
      .catch((exc) => {
        if (!cancelled) {
          const err = toApiError(exc);
          if (err.kind === "forbidden") onForbidden?.();
          setError(err);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // onForbidden is a stable App-level callback; reloadKey/tagFilter drive refetches.
  }, [reloadKey, tagFilter]);

  async function handleOpen(id: string) {
    try {
      const rec = await getSavedScenario(id);
      onOpen({
        result: rec.result,
        analog_events: rec.analog_events_snapshot,
        cache_key: null,
        reproducibility: rec.reproducibility
      });
      // Update URL so refresh re-opens this saved scenario.
      const url = new URL(window.location.href);
      url.searchParams.set("saved", id);
      window.history.replaceState({}, "", url.toString());
    } catch (exc) {
      reportError(exc);
    }
  }

  function requestDelete(item: SavedScenarioListItem) {
    setPendingDelete(item);
    confirmDelete.open();
  }

  async function handleDeleteConfirmed() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteSavedScenario(pendingDelete.id);
      setItems((prev) => prev.filter((i) => i.id !== pendingDelete.id));
      push({ variant: "success", message: "Saved scenario deleted." });
      confirmDelete.close();
      setPendingDelete(null);
    } catch (exc) {
      reportError(exc);
      confirmDelete.close();
    } finally {
      setDeleting(false);
    }
  }

  const allTags = Array.from(new Set(items.flatMap((i) => i.tags))).sort();

  return (
    <section className="result-card saved-panel">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Library</p>
          <h3>Saved scenarios</h3>
        </div>
        <BookMarked size={18} />
      </div>
      {allTags.length > 0 ? (
        <div className="saved-tag-filter">
          <button
            className={tagFilter === "" ? "active" : ""}
            onClick={() => setTagFilter("")}
          >
            All
          </button>
          {allTags.map((tag) => (
            <button
              key={tag}
              className={tagFilter === tag ? "active" : ""}
              onClick={() => setTagFilter(tag)}
            >
              {tag}
            </button>
          ))}
        </div>
      ) : null}
      {error ? <ErrorNotice variant="inline" error={error} /> : null}
      {loading && items.length === 0 ? (
        <p className="muted">Loading...</p>
      ) : items.length === 0 ? (
        <p className="muted">
          No saved scenarios yet. Run a scenario, then click "Save" on the result to
          archive it here.
        </p>
      ) : (
        <ol className="saved-list">
          {items.map((item) => (
            <li key={item.id}>
              <div className="saved-row-head">
                <button className="saved-open" onClick={() => handleOpen(item.id)}>
                  {item.name}
                </button>
                <span className="muted">{relativeTime(item.created_at)}</span>
              </div>
              <div className="saved-row-meta">
                <span>
                  {item.portfolio_name} · as-of {item.effective_as_of_date}
                  {item.narrative_mode === "analog_only" ? " · backdated" : ""}
                </span>
                <span>Total P&amp;L: {formatPercent(item.total_pnl, 2)}</span>
              </div>
              {item.tags.length > 0 ? (
                <div className="saved-tags">
                  {item.tags.map((t) => (
                    <span key={t}>{t}</span>
                  ))}
                </div>
              ) : null}
              <div className="saved-row-actions">
                <a
                  className="ghost-button"
                  href={savedScenarioDownloadUrl(item.id)}
                  download={`nami_${item.portfolio_key}_${slugify(item.name)}_${item.effective_as_of_date}.json`}
                >
                  <Download size={13} /> JSON
                </a>
                <button
                  className="ghost-button danger"
                  onClick={() => requestDelete(item)}
                  aria-label={`Delete ${item.name}`}
                >
                  <Trash2 size={13} /> Delete
                </button>
              </div>
            </li>
          ))}
        </ol>
      )}
      <ConfirmDialog
        isOpen={confirmDelete.isOpen}
        onClose={() => {
          confirmDelete.close();
          setPendingDelete(null);
        }}
        onConfirm={handleDeleteConfirmed}
        title="Delete saved scenario"
        body={
          <p>
            Delete <strong>{pendingDelete?.name ?? "this scenario"}</strong>? This cannot be
            undone.
          </p>
        }
        confirmLabel="Delete"
        danger
        busy={deleting}
      />
    </section>
  );
}
