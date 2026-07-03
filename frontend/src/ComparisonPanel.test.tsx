import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ComparisonPanel } from "./ComparisonPanel";
import type { ScenarioResult, ScenarioRunResponse } from "./types";

function makeResult(overrides: Partial<ScenarioResult> = {}): ScenarioResult {
  return {
    scenario_text: "Broad risk-off with credit stress",
    market_date: "2026-05-28",
    portfolio_key: "us_tech_growth",
    portfolio_name: "US Tech Growth",
    portfolio_holdings: { AAPL: 0.6, MSFT: 0.4 },
    analogs_selected: [],
    factor_shocks: [{ factor: "SPY", shock: -0.1, reasoning: "selloff" }],
    periphery_shocks: [],
    narrative: "n",
    citations: [],
    factor_envelope: {},
    portfolio_pnl: {
      total_pnl: -0.08,
      by_factor_naive: { SPY: -0.08 },
      by_factor_conditional_shapley: null,
      by_factor_conditional_shapley_explicit: null,
      by_factor_conditional_shapley_grouped: null,
      by_ticker_factor: { AAPL: -0.05, MSFT: -0.03 },
      by_ticker_periphery: { AAPL: 0, MSFT: 0 },
      by_ticker_total: { AAPL: -0.05, MSFT: -0.03 }
    },
    narrative_shapley: null,
    adjustment_history: [],
    risk_diagnostics: [],
    severity_ladder: null,
    requested_as_of_date: null,
    narrative_mode: "grounded",
    selected_event_ids: [],
    portfolio_nav: null,
    reporting_currency: null,
    position_quantities: null,
    position_values: null,
    mark_prices: null,
    price_date_by_ticker: null,
    fx_rates: null,
    fx_date_by_currency: null,
    benchmark_ticker: null,
    benchmark_pnl: null,
    active_return: null,
    ...overrides
  } as ScenarioResult;
}

function envelope(result: ScenarioResult): ScenarioRunResponse {
  // cache_key/reproducibility null on purpose — valid on the adjust/decompose/
  // saved paths; the panel must not depend on either.
  return { result, analog_events: {}, cache_key: null, reproducibility: null };
}

describe("ComparisonPanel", () => {
  it("renders A/B/delta headline and factor deltas under one method", () => {
    const pinned = makeResult();
    const current = makeResult({
      factor_shocks: [{ factor: "SPY", shock: -0.05, reasoning: "milder" }],
      portfolio_pnl: {
        ...makeResult().portfolio_pnl,
        total_pnl: -0.04,
        by_factor_naive: { SPY: -0.04 },
        by_ticker_total: { AAPL: -0.02, MSFT: -0.02 }
      }
    });
    render(
      <ComparisonPanel
        pinned={envelope(pinned)}
        current={envelope(current)}
        factorMeta={{}}
        onUnpin={() => {}}
      />
    );
    expect(screen.getByText("Pinned vs current")).toBeInTheDocument();
    expect(screen.getAllByText("-8.00%").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("-4.00%").length).toBeGreaterThanOrEqual(1);
    // delta = current − pinned = +4.00%
    expect(screen.getAllByText("4.00%").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Naive algebra attribution/)).toBeInTheDocument();
    expect(screen.queryByText(/Different books/)).toBeNull();
  });

  it("warns when the books differ and dashes absent-side tickers", () => {
    const pinned = makeResult();
    const current = makeResult({
      portfolio_key: "defensive_mix",
      portfolio_name: "Defensive Mix",
      portfolio_holdings: { KO: 1.0 },
      portfolio_pnl: {
        ...makeResult().portfolio_pnl,
        total_pnl: -0.02,
        by_ticker_total: { KO: -0.02 }
      }
    });
    render(
      <ComparisonPanel
        pinned={envelope(pinned)}
        current={envelope(current)}
        factorMeta={{}}
        onUnpin={() => {}}
      />
    );
    expect(screen.getByText(/Different books/)).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3); // KO pinned side + AAPL/MSFT current side
  });

  it("fires onUnpin", () => {
    const onUnpin = vi.fn();
    render(
      <ComparisonPanel
        pinned={envelope(makeResult())}
        current={envelope(makeResult({ scenario_text: "other" }))}
        factorMeta={{}}
        onUnpin={onUnpin}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Unpin/ }));
    expect(onUnpin).toHaveBeenCalledTimes(1);
  });
});
