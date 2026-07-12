import { useEffect, useMemo, useState } from "react";
import { RotateCcw, Sliders, X } from "lucide-react";
import { adjustScenarioShocks, toApiError } from "./api";
import type { ApiError } from "./api";
import { formatPercent } from "./charts";
import { ErrorNotice } from "./ErrorNotice";
import { factorDisplayName } from "./factors";
import { formatDateTime } from "./format";
import { previewAdjustedPnl } from "./results/adjustPreview";
import { useToasts } from "./toast";
import type {
  FactorMetadataMap,
  ScenarioResult,
  ScenarioRunResponse,
  ShockAdjustment
} from "./types";

interface AdjustmentPanelProps {
  envelope: ScenarioRunResponse;
  canonicalSnapshot: ScenarioResult;
  factorMeta: FactorMetadataMap;
  onResult: (response: ScenarioRunResponse) => void;
  prefillRerun: (text: string) => void;
  onForbidden?: () => void;
}

interface SliderRow {
  factor: string;
  value: number;
}

function rowsFromResult(result: ScenarioResult): SliderRow[] {
  return result.factor_shocks.map((shock) => ({
    factor: shock.factor,
    value: shock.shock
  }));
}

/** Percent-unit display for the number inputs: the raw decimal is the model
 * unit, but every label around the panel reads percent — show percent here
 * too (rounded so float noise never renders as 24.999999...). */
function toPercentInput(value: number): number {
  return Number((value * 100).toFixed(2));
}

export function AdjustmentPanel({
  envelope,
  canonicalSnapshot,
  factorMeta,
  onResult,
  prefillRerun,
  onForbidden
}: AdjustmentPanelProps) {
  const result = envelope.result;
  const cacheKey = envelope.cache_key;
  const { push } = useToasts();

  const [rows, setRows] = useState<SliderRow[]>(() => rowsFromResult(result));
  const [adjustmentText, setAdjustmentText] = useState("");
  const [isAdjusting, setIsAdjusting] = useState(false);
  const [error, setError] = useState<ApiError | string | null>(null);
  const [rerunSuggestion, setRerunSuggestion] = useState<string | null>(null);

  // Reset slider state when a new canonical scenario lands.
  useEffect(() => {
    setRows(rowsFromResult(result));
    setRerunSuggestion(null);
    setError(null);
  }, [result]);

  const canonicalShocks = useMemo(() => {
    const map = new Map<string, number>();
    for (const fs of canonicalSnapshot.factor_shocks) {
      map.set(fs.factor, fs.shock);
    }
    return map;
  }, [canonicalSnapshot]);

  // Presentation partition: rows the server lets the user re-tune (envelope
  // count >= 3) get slider rows; the keep-or-remove majority becomes a chip
  // grid. Both sort by |naive contribution| so the impactful factors lead,
  // matching how the Drivers tab reads. Indices point back into `rows` so
  // setValue keeps working on the canonical-ordered state array (the server
  // requires EVERY canonical key on submit, so `rows` itself never filters).
  const partition = useMemo(() => {
    const naive = result.portfolio_pnl.by_factor_naive;
    const enriched = rows.map((row, index) => {
      const env = result.factor_envelope[row.factor];
      return {
        row,
        index,
        p10: env?.p10 ?? -0.5,
        p90: env?.p90 ?? 0.5,
        count: env?.count ?? 0,
        impact: Math.abs(naive[row.factor] ?? 0)
      };
    });
    const byImpact = (a: { impact: number }, b: { impact: number }) => b.impact - a.impact;
    return {
      tunable: enriched.filter((e) => e.count >= 3).sort(byImpact),
      keepOrRemove: enriched.filter((e) => e.count < 3).sort(byImpact)
    };
  }, [rows, result]);

  const preview = useMemo(() => previewAdjustedPnl(result, rows), [result, rows]);
  const changedFromCanonical = rows.filter(
    (row) => Math.abs(row.value - (canonicalShocks.get(row.factor) ?? row.value)) > 1e-9
  ).length;

  if (!cacheKey) {
    return null;
  }

  function setValue(index: number, value: number) {
    setRows((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], value };
      return next;
    });
  }

  function resetAll() {
    setRows(rowsFromResult(canonicalSnapshot));
  }

  async function applyManual() {
    if (!cacheKey) return;
    setError(null);
    setRerunSuggestion(null);
    setIsAdjusting(true);
    try {
      const overrides: Record<string, number> = {};
      for (const row of rows) {
        overrides[row.factor] = row.value;
      }
      const response = await adjustScenarioShocks({
        cache_key: cacheKey,
        overrides,
        benchmark: result.benchmark_ticker
      });
      onResult(response);
      push({ variant: "success", message: "Adjustment applied." });
    } catch (exc) {
      const err = toApiError(exc);
      if (err.kind === "forbidden") onForbidden?.();
      setError(err);
    } finally {
      setIsAdjusting(false);
    }
  }

  async function applyPrompt() {
    if (!cacheKey || !adjustmentText.trim()) return;
    setError(null);
    setRerunSuggestion(null);
    setIsAdjusting(true);
    try {
      const response = await adjustScenarioShocks({
        cache_key: cacheKey,
        adjustment_text: adjustmentText.trim(),
        benchmark: result.benchmark_ticker
      });
      onResult(response);
      push({ variant: "success", message: "Adjustment applied." });
      setAdjustmentText("");
    } catch (exc) {
      const err = toApiError(exc);
      if (err.kind === "forbidden") onForbidden?.();
      // kind dispatch via X-Error-Code — the rejection_reason detail is LLM
      // free text, so string-matching it can never be sound.
      if (err.kind === "rerun_required") {
        setRerunSuggestion(err.detail);
      } else {
        setError(err);
      }
    } finally {
      setIsAdjusting(false);
    }
  }

  const previewTone =
    preview.total != null ? (preview.total > 0 ? "up" : preview.total < 0 ? "down" : "") : "";

  return (
    <section className="result-card adjustment-card">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Iterate</p>
          <h3>Adjust factor shocks</h3>
          <p className="muted card-subtitle">
            Edits reuse the original narrative and analogs — they run in seconds.
          </p>
        </div>
        <Sliders size={18} />
      </div>

      <div className="adjust-prompt">
        <label htmlFor="adjustment-text">Describe an adjustment</label>
        <textarea
          id="adjustment-text"
          value={adjustmentText}
          onChange={(event) => setAdjustmentText(event.target.value)}
          placeholder='e.g. "make rates shock larger", "remove the credit component"'
          disabled={isAdjusting}
        />
        <button
          className="ghost-button"
          onClick={applyPrompt}
          disabled={isAdjusting || !adjustmentText.trim()}
        >
          Apply adjustment
        </button>
      </div>

      {preview.editedCount > 0 ? (
        <div className="adjust-preview" role="status">
          {preview.total != null ? (
            <span>
              After your edits:{" "}
              <strong className={previewTone}>{formatPercent(preview.total)}</strong>{" "}
              <span className="muted">preview — Recalculate for exact attribution</span>
            </span>
          ) : (
            <span className="muted">
              Preview unavailable for factors re-tuned from 0 — Recalculate for the exact result.
            </span>
          )}
        </div>
      ) : null}

      <div className="button-row adjust-actions">
        <button className="primary-button" onClick={applyManual} disabled={isAdjusting}>
          {isAdjusting ? "Recalculating..." : "Recalculate P&L"}
        </button>
        <button className="ghost-button" onClick={resetAll} disabled={isAdjusting}>
          Reset to canonical
        </button>
        {changedFromCanonical > 0 ? (
          <span className="muted adjust-changed-count">
            {changedFromCanonical} of {rows.length} changed
          </span>
        ) : null}
      </div>

      {partition.tunable.length > 0 ? (
        <>
          <h4 className="adjust-section-title">Fine-tune banded shocks</h4>
          <div className="adjust-tunable">
            {partition.tunable.map(({ row, index, p10, p90 }) => {
              const canonical = canonicalShocks.get(row.factor) ?? row.value;
              const changed = Math.abs(row.value - canonical) > 1e-9;
              const isRemoved = row.value === 0 && canonical !== 0;
              // A single continuous slider can't represent the disjoint valid
              // domain [p10, p90] ∪ {0} when the envelope is entirely one
              // sign. Restrict the slider to [p10, p90]; Remove is the only
              // path to 0, and the slider disables while the value sits
              // outside the band.
              const sliderOutOfRange = row.value < p10 || row.value > p90;
              return (
                <div key={row.factor} className={`adjust-row${changed ? " changed" : ""}`}>
                  <div className="adjust-row-head">
                    <strong>{factorDisplayName(factorMeta, row.factor)}</strong>
                    <span className="muted">
                      envelope {formatPercent(p10, 2)} to {formatPercent(p90, 2)}
                    </span>
                  </div>
                  <div className="adjust-row-controls">
                    <input
                      type="range"
                      min={p10}
                      max={p90}
                      step={0.001}
                      value={row.value}
                      onChange={(event) => setValue(index, Number(event.target.value))}
                      disabled={isAdjusting || sliderOutOfRange}
                      aria-label={`${factorDisplayName(factorMeta, row.factor)} shock (slider)`}
                    />
                    <span className="pct-input">
                      <input
                        type="number"
                        step={0.1}
                        value={toPercentInput(row.value)}
                        onChange={(event) => setValue(index, Number(event.target.value) / 100)}
                        onBlur={() =>
                          setValue(
                            index,
                            row.value === 0 ? 0 : Math.min(p90, Math.max(p10, row.value))
                          )
                        }
                        disabled={isAdjusting}
                        aria-label={`${factorDisplayName(factorMeta, row.factor)} shock value (percent)`}
                      />
                      <span aria-hidden="true">%</span>
                    </span>
                    <button
                      className="ghost-button"
                      onClick={() => setValue(index, isRemoved ? canonical : 0)}
                      disabled={isAdjusting}
                      title={
                        isRemoved
                          ? "Restore this factor's proposed shock"
                          : "Remove this factor from the scenario"
                      }
                    >
                      {isRemoved ? (
                        <>
                          <RotateCcw size={13} /> Restore
                        </>
                      ) : (
                        <>
                          <X size={13} /> Remove
                        </>
                      )}
                    </button>
                  </div>
                  {changed ? (
                    <div className="adjust-row-meta">
                      <span>
                        Canonical {formatPercent(canonical, 2)} {"->"} Current{" "}
                        {formatPercent(row.value, 2)}
                      </span>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </>
      ) : null}

      {partition.keepOrRemove.length > 0 ? (
        <div className="keep-remove">
          <h4 className="adjust-section-title">Keep or remove</h4>
          <p className="muted">
            These shocks have too few analog observations to re-tune (server rule): keep them as
            proposed, or remove them.
          </p>
          <div className="keep-remove-chips">
            {partition.keepOrRemove.map(({ row, index }) => {
              const canonical = canonicalShocks.get(row.factor) ?? row.value;
              const isRemoved = row.value === 0 && canonical !== 0;
              const label = factorDisplayName(factorMeta, row.factor);
              const inert = canonical === 0;
              return (
                <button
                  key={row.factor}
                  type="button"
                  className={`kr-chip${isRemoved ? " removed" : ""}`}
                  aria-pressed={isRemoved}
                  onClick={() => setValue(index, isRemoved ? canonical : 0)}
                  disabled={isAdjusting || inert}
                  title={
                    inert
                      ? "This factor's proposed shock is already 0"
                      : isRemoved
                        ? `Restore ${label} (${formatPercent(canonical, 2)})`
                        : `Remove ${label} from the scenario`
                  }
                >
                  <span className="kr-chip-label">{label}</span>
                  <span className="kr-chip-value">{formatPercent(canonical, 2)}</span>
                  <span className="kr-chip-x" aria-hidden="true">
                    {isRemoved ? <RotateCcw size={12} /> : <X size={12} />}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}

      {error ? (
        <ErrorNotice
          variant="inline"
          error={error}
          onRerun={
            typeof error !== "string" && error.kind === "expired"
              ? () => prefillRerun(result.scenario_text)
              : undefined
          }
        />
      ) : null}
      {rerunSuggestion ? (
        <div className="rerun-suggestion">
          <p>{rerunSuggestion}</p>
          <button
            className="ghost-button"
            onClick={() =>
              prefillRerun(`${result.scenario_text}\n\nAlso: ${adjustmentText.trim()}`)
            }
          >
            Pre-fill rerun in Scenario panel
          </button>
        </div>
      ) : null}

      {result.adjustment_history.length > 0 ? (
        <AdjustmentHistory history={result.adjustment_history} factorMeta={factorMeta} />
      ) : null}
    </section>
  );
}

function AdjustmentHistory({
  history,
  factorMeta
}: {
  history: ShockAdjustment[];
  factorMeta: FactorMetadataMap;
}) {
  return (
    <div className="adjustment-history">
      <h4>Adjustment history</h4>
      <ol>
        {history.map((entry, index) => (
          <li key={index}>
            <span className="kind">{entry.kind}</span>
            <span className="time">{formatDateTime(entry.timestamp)}</span>
            {entry.prompt_text ? <em>{entry.prompt_text}</em> : null}
            <span className="changes">
              {Object.entries(entry.changed_factors)
                .map(
                  ([factor, [before, after]]) =>
                    `${factorDisplayName(factorMeta, factor)}: ${formatPercent(
                      before,
                      2
                    )} -> ${formatPercent(after, 2)}`
                )
                .join(" | ")}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
