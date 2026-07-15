import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScenarioPanel } from "./panels/ScenarioPanel";
import { ResultsPanel } from "./results/ResultsPanel";
import type { AccessResponse, ScenarioResult, ScenarioRunResponse } from "./types";

vi.mock("./PlotLazy", () => ({ PlotLazy: () => <div data-testid="plot" /> }));
vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, getTickerMetadata: vi.fn(() => new Promise(() => {})) };
});

const access: AccessResponse = {
  access_mode: "admin",
  admin_available: true,
  permissions: { custom_portfolio: true, free_text_scenario: true, narrative_decomposition: true },
  latest_market_date: "2026-07-14",
  engine_mode: "quant_v2"
};

function quantResult(): ScenarioResult {
  return {
    scenario_text: "Global shutdown",
    market_date: "2026-07-14",
    portfolio_key: "sample",
    portfolio_name: "Sample",
    portfolio_holdings: { AAPL: 1 },
    analogs_selected: [{ event_id: "covid", why_relevant: "sudden stop" }],
    factor_shocks: [{ factor: "NA:MKT_RF", shock: -0.1, reasoning: "Observed medoid" }],
    periphery_shocks: [],
    narrative: "Grounded narrative.",
    citations: [],
    factor_envelope: {},
    portfolio_pnl: {
      total_pnl: -0.11,
      by_factor_naive: { "NA:MKT_RF": -0.11 },
      by_factor_conditional_shapley: null,
      by_factor_conditional_shapley_explicit: null,
      by_factor_conditional_shapley_grouped: null,
      by_ticker_factor: { AAPL: -0.11 },
      by_ticker_periphery: { AAPL: 0 },
      by_ticker_total: { AAPL: -0.11 }
    },
    narrative_shapley: null,
    adjustment_history: [],
    requested_as_of_date: null,
    narrative_mode: "grounded",
    selected_event_ids: ["covid"],
    engine_mode: "quant_v2",
    methodology: "joint_historical_neighbors",
    horizon_trading_days: 21,
    severity_multiplier: 1.5,
    historical_model_range: {
      label: "historical_model_range",
      p10: -0.18,
      p50: -0.1,
      p90: -0.03,
      draws: 4096,
      seed: 1729
    },
    quant_support: {
      candidate_count: 3000,
      direction_compatible_count: 400,
      neighbor_count: 50,
      effective_sample_size: 41.2,
      medoid_date: "2020-03-16",
      nearest_distance: 0.4,
      kernel_bandwidth: 1.2,
      query_dates: ["2020-03-16"],
      data_start: "2007-07-01",
      data_end: "2026-07-14"
    },
    quant_exposures: {
      AAPL: {
        region: "north_america",
        tier: "estimated",
        n_obs: 156,
        data_weight: 1,
        coefficients: { "NA:MKT_RF": 1.1 }
      }
    }
  };
}

describe("Quant V2 UI", () => {
  it("shows only the two simple run controls when Quant V2 is active", () => {
    const setHorizon = vi.fn();
    const setSeverity = vi.fn();
    render(
      <ScenarioPanel
        access={access}
        scenarios={[]}
        scenarioKey=""
        scenarioDraftMode="custom"
        onSelectScenario={() => {}}
        onSetCustomMode={() => {}}
        scenarioText="Global shutdown"
        setScenarioText={() => {}}
        isRunning={false}
        onRun={() => {}}
        asOfDate="2026-07-14"
        setAsOfDate={() => {}}
        latestClose="2026-07-14"
        horizon={21}
        setHorizon={setHorizon}
        severity={1}
        setSeverity={setSeverity}
      />
    );

    fireEvent.change(screen.getByLabelText("Horizon"), { target: { value: "63" } });
    fireEvent.change(screen.getByLabelText("Severity"), { target: { value: "2" } });
    expect(setHorizon).toHaveBeenCalledWith(63);
    expect(setSeverity).toHaveBeenCalledWith(2);
  });

  it("labels direct attribution and hides adjustment and theme Shapley", () => {
    const result = quantResult();
    const envelope: ScenarioRunResponse = {
      result,
      analog_events: {},
      cache_key: "quant-cache",
      reproducibility: null
    };
    render(
      <ResultsPanel
        envelope={envelope}
        factorMeta={{}}
        displayMode="pct"
        setDisplayMode={() => {}}
        navInput="100000"
        setNavInput={() => {}}
        valuationSort={{ key: "delta", dir: "asc" }}
        setValuationSort={() => {}}
        canAdjust
        canonicalSnapshot={result}
        onAdjustResult={() => {}}
        onPrefillRerun={() => {}}
        canDecompose
        isDecomposing={false}
        decomposeProgress={null}
        onDecompose={() => {}}
        onOpenMethodology={() => {}}
        canSave={false}
        onSave={() => {}}
      />
    );

    expect(screen.getByText("Joint historical model")).toBeInTheDocument();
    expect(screen.getByText("Historical model range")).toBeInTheDocument();
    expect(screen.getByText(/Direct factor contribution/)).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Adjust" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Advanced" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Conditional attribution unavailable/)).not.toBeInTheDocument();
  });
});
