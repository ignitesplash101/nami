import { describe, expect, it } from "vitest";
import { previewAdjustedPnl } from "./adjustPreview";
import type { ScenarioResult } from "../types";

function resultFixture(): ScenarioResult {
  return {
    scenario_text: "Risk-off shock",
    market_date: "2026-05-28",
    portfolio_key: "sample",
    portfolio_name: "Sample book",
    portfolio_holdings: { AAPL: 0.6, MSFT: 0.4 },
    analogs_selected: [],
    factor_shocks: [
      { factor: "SPY", shock: -0.2, reasoning: "selloff" },
      { factor: "TNX", shock: -0.1, reasoning: "rates rally" },
      { factor: "GLD", shock: 0.0, reasoning: "flat" }
    ],
    periphery_shocks: [],
    narrative: "n",
    citations: [],
    factor_envelope: {},
    portfolio_pnl: {
      // exposures: SPY 0.5 (=-0.10/-0.2), TNX 0.2 (=-0.02/-0.1)
      total_pnl: -0.105,
      by_factor_naive: { SPY: -0.1, TNX: -0.02, GLD: 0 },
      by_factor_conditional_shapley: null,
      by_factor_conditional_shapley_explicit: null,
      by_factor_conditional_shapley_grouped: null,
      by_ticker_factor: { AAPL: -0.08, MSFT: -0.04 },
      by_ticker_periphery: { AAPL: 0.01, MSFT: 0.005 },
      by_ticker_total: { AAPL: -0.07, MSFT: -0.035 }
    },
    narrative_shapley: null,
    adjustment_history: [],
    requested_as_of_date: null,
    narrative_mode: "grounded",
    selected_event_ids: []
  };
}

const PERIPHERY = 0.015;

describe("previewAdjustedPnl", () => {
  it("reproduces the current total when nothing is edited", () => {
    const result = resultFixture();
    const rows = result.factor_shocks.map((fs) => ({ factor: fs.factor, value: fs.shock }));
    const preview = previewAdjustedPnl(result, rows);
    expect(preview.editedCount).toBe(0);
    // periphery + Σ by_factor_naive = 0.015 + (-0.12) = -0.105 = total_pnl
    expect(preview.total).toBeCloseTo(result.portfolio_pnl.total_pnl, 10);
  });

  it("scales an edited factor's contribution linearly (exact under naive algebra)", () => {
    const result = resultFixture();
    const rows = [
      { factor: "SPY", value: -0.3 }, // exposure 0.5 → contribution -0.15
      { factor: "TNX", value: -0.1 },
      { factor: "GLD", value: 0.0 }
    ];
    const preview = previewAdjustedPnl(result, rows);
    expect(preview.editedCount).toBe(1);
    expect(preview.total).toBeCloseTo(PERIPHERY + -0.15 + -0.02, 10);
  });

  it("drops a removed factor's contribution entirely", () => {
    const result = resultFixture();
    const rows = [
      { factor: "SPY", value: 0 },
      { factor: "TNX", value: -0.1 },
      { factor: "GLD", value: 0 }
    ];
    const preview = previewAdjustedPnl(result, rows);
    expect(preview.total).toBeCloseTo(PERIPHERY + 0 + -0.02, 10);
  });

  it("returns null when a factor is re-tuned FROM zero (exposure underivable)", () => {
    const result = resultFixture();
    const rows = [
      { factor: "SPY", value: -0.2 },
      { factor: "TNX", value: -0.1 },
      { factor: "GLD", value: 0.05 }
    ];
    const preview = previewAdjustedPnl(result, rows);
    expect(preview.editedCount).toBe(1);
    expect(preview.total).toBeNull();
  });
});
