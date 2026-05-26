import { useEffect, useState } from "react";
import { BookMarked, Download, Trash2 } from "lucide-react";
import {
  deleteSavedScenario,
  getSavedScenario,
  listSavedScenarios,
  savedScenarioDownloadUrl
} from "./api";
import { formatPercent } from "./charts";
import type { ScenarioRunResponse, SavedScenarioListItem } from "./types";

interface SavedScenariosPanelProps {
  reloadKey: number;  // bump to trigger refresh after a new save
  onOpen: (envelope: ScenarioRunResponse) => void;
}

function relativeTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(ms / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function SavedScenariosPanel({ reloadKey, onOpen }: SavedScenariosPanelProps) {
  const [items, setItems] = useState<SavedScenarioListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [tagFilter, setTagFilter] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listSavedScenarios(tagFilter || undefined)
      .then((data) => {
        if (!cancelled) setItems(data);
      })
      .catch((exc) => {
        if (!cancelled) setError(exc instanceof Error ? exc.message : String(exc));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
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
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this saved scenario? This cannot be undone.")) return;
    try {
      await deleteSavedScenario(id);
      setItems((prev) => prev.filter((i) => i.id !== id));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
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
      {error ? <div className="inline-error">{error}</div> : null}
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
                  download
                >
                  <Download size={13} /> JSON
                </a>
                <button
                  className="ghost-button danger"
                  onClick={() => handleDelete(item.id)}
                  aria-label={`Delete ${item.name}`}
                >
                  <Trash2 size={13} /> Delete
                </button>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
