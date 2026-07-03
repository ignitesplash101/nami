import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SeverityLadderStrip } from "./App";
import type { ScenarioResult, SeverityLadder } from "./types";

vi.mock("react-plotly.js", () => ({
  default: () => <div data-testid="plot" />
}));

function resultWithLadder(ladder: SeverityLadder | null): ScenarioResult {
  return {
    scenario_text: "Risk-off shock",
    market_date: "2026-05-28",
    portfolio_key: "sample",
    portfolio_name: "Sample book",
    portfolio_holdings: { AAPL: 1.0 },
    analogs_selected: [],
    factor_shocks: [{ factor: "SPY", shock: -0.1, reasoning: "broad selloff" }],
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
      by_ticker_factor: { AAPL: -0.08 },
      by_ticker_periphery: { AAPL: 0 },
      by_ticker_total: { AAPL: -0.08 }
    },
    narrative_shapley: null,
    adjustment_history: [],
    risk_diagnostics: [],
    severity_ladder: ladder,
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
    active_return: null
  } as ScenarioResult;
}

describe("SeverityLadderStrip", () => {
  it("renders the envelope bounds range with counts", () => {
    render(
      <SeverityLadderStrip
        result={resultWithLadder({
          worst_pnl: -0.15,
          base_pnl: -0.08,
          best_pnl: -0.02,
          n_banded: 3,
          n_held: 1
        })}
        showDollars={false}
        nav={null}
        currency="USD"
      />
    );
    expect(screen.getByText(/Severity ladder — envelope bounds/)).toBeInTheDocument();
    expect(screen.getByText("-15.00%")).toBeInTheDocument();
    expect(screen.getByText("-2.00%")).toBeInTheDocument();
    expect(screen.getByText("-8.00%")).toBeInTheDocument();
    expect(screen.getByText(/3 banded factor shocks/)).toBeInTheDocument();
    expect(screen.getByText(/1 low-evidence shock held/)).toBeInTheDocument();
  });

  it("dollarizes with a NAV in dollar mode", () => {
    render(
      <SeverityLadderStrip
        result={resultWithLadder({
          worst_pnl: -0.15,
          base_pnl: -0.08,
          best_pnl: -0.02,
          n_banded: 2,
          n_held: 0
        })}
        showDollars={true}
        nav={100000}
        currency="USD"
      />
    );
    expect(screen.getByText("-$15,000")).toBeInTheDocument();
    expect(screen.queryByText(/low-evidence/)).toBeNull();
  });

  it("renders nothing on payloads without a ladder (older canonicals)", () => {
    const { container } = render(
      <SeverityLadderStrip
        result={resultWithLadder(null)}
        showDollars={false}
        nav={null}
        currency="USD"
      />
    );
    expect(container).toBeEmptyDOMElement();
  });
});
