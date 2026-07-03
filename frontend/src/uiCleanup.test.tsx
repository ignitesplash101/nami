import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ResultsPanel, ScenarioPanel } from "./App";
import type { AccessResponse, ScenarioResult, ScenarioRunResponse } from "./types";

vi.mock("./PlotLazy", () => ({
  PlotLazy: () => <div data-testid="plot" />
}));

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    getTickerMetadata: vi.fn(() => new Promise(() => {}))
  };
});

function visitorAccess(): AccessResponse {
  return {
    access_mode: "visitor",
    admin_available: true,
    latest_market_date: "2026-05-28",
    permissions: {
      custom_portfolio: false,
      free_text_scenario: false,
      narrative_decomposition: false
    }
  };
}

function resultFixture(): ScenarioResult {
  return {
    scenario_text: "Risk-off shock",
    market_date: "2026-05-28",
    portfolio_key: "sample",
    portfolio_name: "Sample book",
    portfolio_holdings: { AAPL: 0.6, MSFT: 0.4 },
    analogs_selected: [{ event_id: "event-1", why_relevant: "same transmission path" }],
    factor_shocks: [{ factor: "SPY", shock: -0.1, reasoning: "broad selloff" }],
    periphery_shocks: [],
    narrative: "A risk-off move pressures growth equities.",
    citations: [{ title: "Source", url: "https://example.com", snippet: null }],
    factor_envelope: {},
    portfolio_pnl: {
      total_pnl: -0.08,
      by_factor_naive: { SPY: -0.06 },
      by_factor_conditional_shapley: null,
      by_factor_conditional_shapley_explicit: null,
      by_factor_conditional_shapley_grouped: null,
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

function envelopeFixture(): ScenarioRunResponse {
  return {
    result: resultFixture(),
    analog_events: {
      "event-1": {
        event_id: "event-1",
        name: "Analog event",
        start_date: "2020-01-01",
        end_date: "2020-02-01",
        tags: ["risk"],
        description: "Risk-off analog"
      }
    },
    cache_key: null,
    reproducibility: null
  };
}

function renderResults(
  envelope: ScenarioRunResponse | null,
  overrides: {
    isRunning?: boolean;
    isStale?: boolean;
    onSeedScenario?: (key: string) => void;
    onProfileBook?: () => void;
    onEventsReplay?: () => void;
  } = {}
) {
  return render(
    <ResultsPanel
      envelope={envelope}
      attributionMethod="naive"
      setAttributionMethod={() => {}}
      factorMeta={{}}
      displayMode="pct"
      setDisplayMode={() => {}}
      navInput="100000"
      setNavInput={() => {}}
      valuationSort={{ key: "delta", dir: "asc" }}
      setValuationSort={() => {}}
      isRunning={overrides.isRunning ?? false}
      isStale={overrides.isStale ?? false}
      sampleScenarios={[
        { key: "covid", name: "COVID-like pandemic shock", text: "Pandemic shock text" },
        { key: "tariffs", name: "China tariff escalation", text: "Tariff shock text" }
      ]}
      onSeedScenario={overrides.onSeedScenario ?? (() => {})}
      onProfileBook={overrides.onProfileBook}
      onEventsReplay={overrides.onEventsReplay}
      canDecompose={false}
      isDecomposing={false}
      decomposeProgress={null}
      onDecompose={() => {}}
      onOpenMethodology={() => {}}
      canSave={false}
      onSave={() => {}}
    />
  );
}

describe("first-screen UI cleanup", () => {
  it("uses chips as the only sample-scenario selector in visitor mode", () => {
    render(
      <ScenarioPanel
        access={visitorAccess()}
        scenarios={[
          { key: "covid", name: "COVID-like pandemic shock", text: "Pandemic shock text" },
          { key: "tariffs", name: "China tariff escalation", text: "Tariff shock text" }
        ]}
        scenarioKey="covid"
        scenarioDraftMode="sample"
        onSelectScenario={() => {}}
        onSetCustomMode={() => {}}
        scenarioText="Pandemic shock text"
        setScenarioText={() => {}}
        selectedScenario={{
          key: "covid",
          name: "COVID-like pandemic shock",
          text: "Pandemic shock text"
        }}
        isRunning={false}
        onRun={() => {}}
        asOfDate="2026-05-28"
        setAsOfDate={() => {}}
        latestClose="2026-05-28"
      />
    );

    expect(screen.getByRole("group", { name: "Example scenarios" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Sample scenario")).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Scenario text/)).toBeEnabled();
    expect(screen.getByRole("button", { name: "Custom" })).toBeInTheDocument();
  });

  it("renders a one-line onboarding empty state with the Know-this-book card", () => {
    const onProfileBook = vi.fn();
    const onEventsReplay = vi.fn();
    renderResults(null, { onProfileBook, onEventsReplay });

    expect(screen.getByLabelText("Scenario results")).toHaveClass("onboarding-empty");
    expect(screen.getByText("No scenario run yet")).toBeInTheDocument();
    expect(screen.getByText(/Pick a book in the rail/)).toBeInTheDocument();
    // the duplicated seed chips are gone — the scenario card above is the selector
    expect(screen.queryByRole("group", { name: "Try a sample scenario" })).toBeNull();

    // the two free analytics live behind one segmented card
    expect(screen.getByText(/Know this book — free, no LLM/)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Book profile" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Event replay" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Profile this book" }));
    expect(onProfileBook).toHaveBeenCalledTimes(1);
  });

  it("shows a shimmer skeleton on the first run and a stale dim on re-runs", () => {
    renderResults(null, { isRunning: true });
    expect(screen.getByLabelText("Scenario results")).toHaveClass("results-skeleton");
    expect(screen.getByLabelText("Scenario results")).toHaveAttribute("aria-busy", "true");
    cleanup();

    renderResults(envelopeFixture(), { isRunning: true, isStale: true });
    const stack = document.querySelector(".results-stack");
    expect(stack).toHaveClass("is-stale");
    expect(stack).toHaveAttribute("aria-busy", "true");
  });

  it("keeps summary facts in the readout instead of duplicating them as metric cards", () => {
    renderResults(envelopeFixture());

    expect(screen.getAllByText("Portfolio P&L")).toHaveLength(1);
    expect(screen.getByText("Top driver")).toBeInTheDocument();
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.queryByText("Top contributor")).not.toBeInTheDocument();
    expect(screen.queryByText("Analogs")).not.toBeInTheDocument();
    expect(screen.queryByText("Citations")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Portfolio value details")).toHaveTextContent("Portfolio NAV");
  });
});
