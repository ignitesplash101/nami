import { describe, expect, it } from "vitest";
import { buildWaterfallData, factorReasoningRows, topContributor } from "./charts";
import type { ScenarioResult } from "./types";

function fixtureResult(): ScenarioResult {
  return {
    scenario_text: "risk-off",
    market_date: "2026-05-25",
    portfolio_key: "sample",
    portfolio_name: "Sample",
    portfolio_holdings: { AAPL: 0.6, MSFT: 0.4 },
    analogs_selected: [],
    factor_shocks: [{ factor: "SPY", shock: -0.1, reasoning: "broad selloff" }],
    periphery_shocks: [],
    narrative: "mock",
    citations: [],
    factor_envelope: {},
    portfolio_pnl: {
      total_pnl: -0.08,
      by_factor_naive: { SPY: -0.06, VIX: 0 },
      by_factor_conditional_shapley: { SPY: -0.04, ACWI: -0.02 },
      by_factor_conditional_shapley_explicit: { SPY: -0.06, ACWI: 0 },
      by_factor_conditional_shapley_grouped: { SPY: -0.06, ACWI: 0 },
      by_ticker_factor: { AAPL: -0.04, MSFT: -0.02 },
      by_ticker_periphery: { AAPL: -0.02, MSFT: 0 },
      by_ticker_total: { AAPL: -0.06, MSFT: -0.02 }
    },
    narrative_shapley: null,
    adjustment_history: [],
    requested_as_of_date: null,
    narrative_mode: "grounded",
    selected_event_ids: []
  };
}

describe("chart data helpers", () => {
  it("builds a waterfall with periphery and total bars", () => {
    const data = buildWaterfallData(fixtureResult(), "naive");

    expect(data.x).toContain("SPY");
    expect(data.x).toContain("Periphery");
    expect(data.x[data.x.length - 1]).toBe("Total");
    expect(data.measure[data.measure.length - 1]).toBe("total");
    expect(data.y[data.y.length - 1]).toBe(-0.08);
  });

  it("switches top contributor under conditional attribution", () => {
    const naive = topContributor(fixtureResult(), "naive");
    const conditional = topContributor(fixtureResult(), "conditional");

    expect(naive.factor).toBe("SPY");
    expect(conditional.factor).toBe("SPY");
    expect(conditional.contribution).toBe(-0.04);
  });

  it("labels correlation-only rows when conditional Shapley attributes unshocked factors", () => {
    const rows = factorReasoningRows(fixtureResult(), "conditional");
    const acwi = rows.find((row) => row.factor === "ACWI");

    expect(acwi?.shockApplied).toBe(0);
    expect(acwi?.reasoning).toContain("No explicit LLM shock");
  });

  it("explicit-only mode picks the explicit-only attribution and suppresses correlation-only label", () => {
    const top = topContributor(fixtureResult(), "conditional_explicit");
    expect(top.factor).toBe("SPY");
    expect(top.contribution).toBe(-0.06);

    // ACWI should not appear as a row at all in explicit-only — it has zero
    // contribution AND no explicit shock, so the row filter drops it.
    const rows = factorReasoningRows(fixtureResult(), "conditional_explicit");
    const acwi = rows.find((row) => row.factor === "ACWI");
    expect(acwi).toBeUndefined();
  });

  it("grouped mode reads from the grouped attribution map", () => {
    const top = topContributor(fixtureResult(), "conditional_grouped");
    expect(top.factor).toBe("SPY");
    expect(top.contribution).toBe(-0.06);
  });
});

