import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvidenceBlock } from "./EvidenceBlock";
import type { ScenarioResult } from "./types";

function makeResult(overrides: Partial<ScenarioResult> = {}): ScenarioResult {
  return {
    scenario_text: "Risk-off",
    market_date: "2026-05-28",
    portfolio_key: "sample",
    portfolio_name: "Sample book",
    portfolio_holdings: { AAPL: 1.0 },
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
      by_ticker_factor: { AAPL: -0.08 },
      by_ticker_periphery: { AAPL: 0 },
      by_ticker_total: { AAPL: -0.08 }
    },
    narrative_shapley: null,
    adjustment_history: [],
    risk_diagnostics: [],
    analog_replay: {
      per_event: [
        { event_id: "covid-crash-2020", replay_pnl: -0.19, n_factors_covered: 26, n_factors_total: 26 },
        { event_id: "lehman-gfc-2008", replay_pnl: -0.12, n_factors_covered: 19, n_factors_total: 26 }
      ],
      min_pnl: -0.19,
      median_pnl: -0.155,
      max_pnl: -0.12
    },
    pnl_uncertainty: { band_1sigma: 0.011, portfolio_idio_vol_weekly: 0.005, horizon_weeks: 5 },
    severity_ladder: { worst_pnl: -0.15, base_pnl: -0.08, best_pnl: -0.02, n_banded: 3, n_held: 1 },
    requested_as_of_date: null,
    narrative_mode: "grounded",
    selected_event_ids: ["covid-crash-2020", "lehman-gfc-2008"],
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

const EVENTS = {
  "covid-crash-2020": {
    event_id: "covid-crash-2020",
    name: "COVID-19 Crash",
    start_date: "2020-02-19",
    end_date: "2020-03-23",
    tags: [],
    description: ""
  },
  "lehman-gfc-2008": {
    event_id: "lehman-gfc-2008",
    name: "Lehman / GFC",
    start_date: "2008-09-15",
    end_date: "2008-10-31",
    tags: [],
    description: ""
  }
};

describe("EvidenceBlock", () => {
  it("renders every layer with the merged honesty caption (phrases verbatim)", () => {
    render(
      <EvidenceBlock
        result={makeResult()}
        analogEvents={EVENTS}
        showDollars={false}
        nav={null}
        currency="USD"
      />
    );
    expect(screen.getByText(/Evidence & bounds/)).toBeInTheDocument();
    expect(screen.getByText("Scenario (base)")).toBeInTheDocument();
    expect(screen.getByText(/±1σ idio dispersion/)).toBeInTheDocument();
    expect(screen.getAllByText(/Envelope bounds/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/3 banded · 1 held/)).toBeInTheDocument();
    expect(screen.getByText(/Analog replay/)).toBeInTheDocument();
    // honesty phrases, verbatim
    expect(screen.getByText(/dispersion floor — not a confidence interval/)).toBeInTheDocument();
    expect(
      screen.getByText(/an evidence-base bound, not a joint scenario/)
    ).toBeInTheDocument();
    expect(screen.getByText(/historical replay, not a forecast/)).toBeInTheDocument();
    // per-analog disclosure content
    expect(screen.getByText("Per-analog replay detail (2)")).toBeInTheDocument();
    expect(screen.getByText("COVID-19 Crash")).toBeInTheDocument();
    expect(screen.getByText("19/26 factors")).toBeInTheDocument();
  });

  it("renders partial layers on older payloads and drops their caption clauses", () => {
    render(
      <EvidenceBlock
        result={makeResult({ severity_ladder: null, pnl_uncertainty: null })}
        analogEvents={EVENTS}
        showDollars={false}
        nav={null}
        currency="USD"
      />
    );
    expect(screen.getByText(/Analog replay/)).toBeInTheDocument();
    expect(screen.queryByText(/Envelope bounds/)).toBeNull();
    expect(screen.queryByText(/±1σ idio dispersion/)).toBeNull();
    expect(screen.queryByText(/not a joint scenario/)).toBeNull();
    expect(screen.getByText(/historical replay, not a forecast/)).toBeInTheDocument();
  });

  it("renders nothing when the payload carries no evidence layer at all", () => {
    const { container } = render(
      <EvidenceBlock
        result={makeResult({ severity_ladder: null, pnl_uncertainty: null, analog_replay: null })}
        analogEvents={EVENTS}
        showDollars={false}
        nav={null}
        currency="USD"
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("dollarizes in dollar mode", () => {
    render(
      <EvidenceBlock
        result={makeResult()}
        analogEvents={EVENTS}
        showDollars={true}
        nav={100000}
        currency="USD"
      />
    );
    expect(screen.getByText("-$8,000")).toBeInTheDocument(); // base
    expect(screen.getAllByText(/-\$15,000/).length).toBeGreaterThanOrEqual(1); // ladder worst
  });
});
