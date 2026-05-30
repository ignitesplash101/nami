import { useEffect, useMemo, useState } from "react";
import { Sliders, X } from "lucide-react";
import { adjustScenarioShocks } from "./api";
import { formatPercent } from "./charts";
import type { ScenarioResult, ScenarioRunResponse, ShockAdjustment } from "./types";

interface AdjustmentPanelProps {
  envelope: ScenarioRunResponse;
  canonicalSnapshot: ScenarioResult;
  onResult: (response: ScenarioRunResponse) => void;
  prefillRerun: (text: string) => void;
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

function formatBefore(value: number, digits = 2): string {
  return formatPercent(value, digits);
}

export function AdjustmentPanel({
  envelope,
  canonicalSnapshot,
  onResult,
  prefillRerun
}: AdjustmentPanelProps) {
  const result = envelope.result;
  const cacheKey = envelope.cache_key;

  const [rows, setRows] = useState<SliderRow[]>(() => rowsFromResult(result));
  const [adjustmentText, setAdjustmentText] = useState("");
  const [isAdjusting, setIsAdjusting] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
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
      setAdjustmentText("");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      // 422 from the backend means scope=rerun_required: surface a rerun CTA.
      if (/rerun|requires a full/i.test(message)) {
        setRerunSuggestion(message);
      } else {
        setError(message);
      }
    } finally {
      setIsAdjusting(false);
    }
  }

  return (
    <section className="result-card adjustment-card">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Iterate</p>
          <h3>Adjust factor shocks</h3>
        </div>
        <Sliders size={18} />
      </div>
      <p className="muted">
        Edit shock magnitudes inside each factor&apos;s envelope, or describe an adjustment in
        natural language. Removing a factor (0.0) is always permitted; other values must lie in
        the analog envelope. Edits run in seconds — they reuse the original narrative and
        analogs.
      </p>

      <div className="adjust-sliders">
        {rows.map((row, index) => {
          const env = result.factor_envelope[row.factor];
          const p10 = env?.p10 ?? -0.5;
          const p90 = env?.p90 ?? 0.5;
          const canonical = canonicalShocks.get(row.factor) ?? row.value;
          const changedFromCanonical = Math.abs(row.value - canonical) > 1e-9;
          const isRemoved = row.value === 0 && canonical !== 0;
          // A single continuous slider can't represent the disjoint valid domain
          // [p10, p90] ∪ {0} when the envelope is entirely one sign. Restrict the
          // slider to [p10, p90]; the Remove button is the only path to 0. Disable
          // the slider whenever the current value sits outside [p10, p90].
          const sliderOutOfRange = row.value < p10 || row.value > p90;
          return (
            <div key={row.factor} className={`adjust-row${changedFromCanonical ? " changed" : ""}`}>
              <div className="adjust-row-head">
                <strong>{row.factor}</strong>
                <span className="muted">
                  envelope {formatBefore(p10, 2)} to {formatBefore(p90, 2)}
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
                  aria-label={`${row.factor} shock (slider)`}
                />
                <input
                  type="number"
                  step={0.001}
                  value={row.value}
                  onChange={(event) => setValue(index, Number(event.target.value))}
                  onBlur={() =>
                    setValue(
                      index,
                      row.value === 0 ? 0 : Math.min(p90, Math.max(p10, row.value))
                    )
                  }
                  disabled={isAdjusting}
                  aria-label={`${row.factor} shock value`}
                />
                <button
                  className="ghost-button"
                  onClick={() => setValue(index, 0)}
                  disabled={isAdjusting || isRemoved}
                  title="Remove this factor from the scenario"
                >
                  <X size={13} /> Remove
                </button>
              </div>
              <div className="adjust-row-meta">
                <span>
                  Canonical {formatPercent(canonical, 2)} {"->"} Current {formatPercent(row.value, 2)}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="button-row">
        <button className="primary-button" onClick={applyManual} disabled={isAdjusting}>
          {isAdjusting ? "Recalculating..." : "Recalculate P&L"}
        </button>
        <button className="ghost-button" onClick={resetAll} disabled={isAdjusting}>
          Reset to canonical
        </button>
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

      {error ? (
        <div className="inline-error" role="alert">
          {error}
        </div>
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
        <AdjustmentHistory history={result.adjustment_history} />
      ) : null}
    </section>
  );
}

function AdjustmentHistory({ history }: { history: ShockAdjustment[] }) {
  return (
    <div className="adjustment-history">
      <h4>Adjustment history</h4>
      <ol>
        {history.map((entry, index) => (
          <li key={index}>
            <span className="kind">{entry.kind}</span>
            <span className="time">{new Date(entry.timestamp).toLocaleTimeString()}</span>
            {entry.prompt_text ? <em>{entry.prompt_text}</em> : null}
            <span className="changes">
              {Object.entries(entry.changed_factors)
                .map(
                  ([factor, [before, after]]) =>
                    `${factor}: ${formatPercent(before, 2)} -> ${formatPercent(after, 2)}`
                )
                .join(" | ")}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
