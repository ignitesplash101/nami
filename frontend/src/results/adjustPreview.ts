import type { ScenarioResult } from "../types";

export interface AdjustRow {
  factor: string;
  value: number;
}

export interface AdjustPreview {
  /** Previewed total P&L (decimal); null when underivable (see below). */
  total: number | null;
  /** Rows whose value differs from the displayed result's shock. */
  editedCount: number;
}

/** Client-side preview of the adjusted headline P&L. Exact under the linear
 * engine's NAIVE algebra: `by_factor_naive[f] = exposure_f × shock_f`, so
 * `exposure_f = contrib_f / shock_f` for shock ≠ 0, and the previewed total is
 * the (shock-independent) periphery total plus Σ exposure_f × new_shock_f.
 * The Conditional-Shapley maps redistribute credit and can NOT be previewed
 * this way — the UI labels the number "preview" and Recalculate stays the
 * exact path. `total` is null when any EDITED factor's current shock is 0:
 * its exposure is underivable client-side (0/0). */
export function previewAdjustedPnl(result: ScenarioResult, rows: AdjustRow[]): AdjustPreview {
  const peripheryTotal = Object.values(result.portfolio_pnl.by_ticker_periphery).reduce(
    (acc, value) => acc + value,
    0
  );
  const currentShocks = new Map(result.factor_shocks.map((fs) => [fs.factor, fs.shock]));
  const naive = result.portfolio_pnl.by_factor_naive;

  let total = peripheryTotal;
  let editedCount = 0;
  let underivable = false;
  for (const row of rows) {
    const current = currentShocks.get(row.factor) ?? 0;
    const contribution = naive[row.factor] ?? 0;
    if (row.value === current) {
      total += contribution;
      continue;
    }
    editedCount += 1;
    if (current === 0) {
      underivable = true;
      continue;
    }
    total += (contribution / current) * row.value;
  }
  return { total: underivable ? null : total, editedCount };
}
