import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { buildHoldingImpactModel, buildTransmissionModel } from "../impact";
import type { ScenarioResult, ScenarioRunResponse } from "../types";
import { HoldingImpactChart } from "./HoldingImpactChart";
import { ResultsPanel } from "./ResultsPanel";
import { ScenarioReadout } from "./ScenarioReadout";
import { TransmissionChart } from "./TransmissionChart";

vi.mock("./WaterfallChart", () => ({
  WaterfallChart: () => <div data-testid="waterfall-chart" />
}));

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, getTickerMetadata: vi.fn(() => new Promise(() => {})) };
});

const FACTORS = ["XLK", "SPY", "XLI", "VIX", "TNX", "OIL", "GLD", "ACWI", "XLF", "HYG"];

function result(overrides: Partial<ScenarioResult> = {}): ScenarioResult {
  const contributions = Object.fromEntries(
    FACTORS.map((factor, index) => [factor, -0.01 * (FACTORS.length - index)])
  );
  return {
    scenario_text: "tariffs",
    market_date: "2026-11-04",
    portfolio_key: "tech",
    portfolio_name: "Tech",
    portfolio_holdings: { AAPL: 0.6, MSFT: 0.4 },
    analogs_selected: [{ event_id: "q4-2018", why_relevant: "trade war" }],
    factor_shocks: FACTORS.map((factor) => ({
      factor,
      shock: -0.05,
      reasoning: `${factor} reprices on tariffs`
    })),
    periphery_shocks: [],
    narrative: "",
    citations: [],
    factor_envelope: {},
    portfolio_pnl: {
      total_pnl: -0.55,
      by_factor_naive: contributions,
      by_factor_conditional_shapley: null,
      by_factor_conditional_shapley_explicit: contributions,
      by_factor_conditional_shapley_grouped: null,
      by_ticker_factor: { AAPL: -0.33, MSFT: -0.22 },
      by_ticker_periphery: { AAPL: 0, MSFT: 0 },
      by_ticker_total: { AAPL: -0.33, MSFT: -0.22 }
    },
    narrative_shapley: null,
    adjustment_history: [],
    requested_as_of_date: null,
    narrative_mode: "grounded",
    selected_event_ids: [],
    analog_event_returns: [
      { event_id: "q4-2018", window_calendar_days: 91, factor_returns: { XLK: -0.178 } }
    ],
    ...overrides
  };
}

const EVENTS = {
  "q4-2018": {
    event_id: "q4-2018",
    name: "Q4 2018 trade war",
    start_date: "2018-10-01",
    end_date: "2018-12-31",
    tags: [],
    description: ""
  }
};

function renderChart(props: Partial<Parameters<typeof TransmissionChart>[0]> = {}) {
  const model = buildTransmissionModel(result(), "conditional_explicit", undefined, EVENTS)!;
  return render(
    <TransmissionChart
      model={model}
      showDollars={false}
      nav={null}
      currency="USD"
      degraded={false}
      initialRows={8}
      {...props}
    />
  );
}

describe("TransmissionChart", () => {
  it("shows the largest drivers first and reveals the rest on request", () => {
    renderChart();
    const chart = screen.getByRole("group", { name: "How the scenario reaches this portfolio" });
    expect(within(chart).getAllByRole("listitem").filter((li) => li.classList.contains("tx-row"))).toHaveLength(8);
    const more = screen.getByRole("button", { name: "Show all 10 drivers" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(more);
    expect(document.querySelectorAll(".tx-row")).toHaveLength(10);
    expect(screen.getByRole("button", { name: "Show the largest drivers only" })).toHaveAttribute(
      "aria-expanded",
      "true"
    );
  });

  it("names each row's move, matched-event moves, and P&L effect for assistive tech", () => {
    renderChart();
    const row = screen.getByRole("button", { name: /^US technology \(XLK\): scenario move -5\.0%/ });
    expect(row).toHaveAccessibleName(
      "US technology (XLK): scenario move -5.0%; in 1 matched events it moved -17.8%; effect on P&L -10.00%. Show reasoning."
    );
  });

  it("expands a row into its reasoning and the per-event moves", () => {
    renderChart();
    const row = screen.getByRole("button", { name: /^US technology \(XLK\)/ });
    const detail = document.getElementById(row.getAttribute("aria-controls")!)!;
    expect(detail).not.toBeVisible();
    fireEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(detail).toBeVisible();
    expect(within(detail).getByText("XLK reprices on tariffs")).toBeInTheDocument();
    expect(within(detail).getByText("Q4 2018 trade war")).toBeInTheDocument();
    expect(within(detail).getByText("-17.8%")).toBeInTheDocument();
  });

  it("formats effects in dollars when a NAV drives the dollar view, shocks stay in percent", () => {
    renderChart({ showDollars: true, nav: 100_000 });
    const row = screen.getByRole("button", { name: /^US technology \(XLK\)/ });
    expect(within(row).getByText("-$10,000")).toBeInTheDocument();
    expect(within(row).getByText("-5.0%")).toBeInTheDocument();
    expect(screen.getByText("Modeled total").nextElementSibling).toHaveTextContent("-$55,000");
  });

  it("switches the effect explainer to the naive algebra on degraded results", () => {
    renderChart({ degraded: true });
    fireEvent.click(screen.getByRole("button", { name: "About the effect on your P&L" }));
    expect(screen.getByText(/naive exposure × shock/)).toBeInTheDocument();
  });
});

describe("HoldingImpactChart", () => {
  it("ranks holdings with weight and modeled move, and labels each row", () => {
    const model = buildHoldingImpactModel(result())!;
    render(
      <HoldingImpactChart model={model} showDollars={false} nav={null} currency="USD" initialRows={1} />
    );
    expect(screen.getByLabelText("AAPL: 60.0% of the book, modeled move -55.0%; effect on P&L -33.00%")).toBeInTheDocument();
    expect(screen.queryByText("MSFT")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show all 2 holdings" }));
    expect(screen.getByText("MSFT")).toBeInTheDocument();
  });
});

function envelope(resultOverrides: Partial<ScenarioResult> = {}): ScenarioRunResponse {
  return {
    result: result(resultOverrides),
    analog_events: EVENTS,
    cache_key: null,
    reproducibility: null
  };
}

function renderPanel(env: ScenarioRunResponse) {
  return render(
    <ResultsPanel
      envelope={env}
      factorMeta={{}}
      displayMode="pct"
      setDisplayMode={() => {}}
      navInput=""
      setNavInput={() => {}}
      valuationSort={{ key: "delta", dir: "asc" }}
      setValuationSort={() => {}}
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

describe("Drivers card views (Phase 43)", () => {
  it("lands on the move → effect chart and keeps the waterfall one click away", () => {
    renderPanel(envelope());
    expect(screen.getByRole("radio", { name: "Move → effect" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("group", { name: "How the scenario reaches this portfolio" })).toBeInTheDocument();
    expect(screen.queryByTestId("waterfall-chart")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "Waterfall" }));
    expect(screen.getByTestId("waterfall-chart")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "By group" }));
    expect(screen.getByTestId("waterfall-chart")).toBeInTheDocument();
  });

  it("collapses informational diagnostics behind one line and opens on warnings", () => {
    const info = {
      kind: "conditional_cross_credit" as const,
      severity: "info" as const,
      message: "correlation credit only",
      factors: ["EFA"],
      evidence: {}
    };
    const { unmount } = renderPanel(envelope({ risk_diagnostics: [info, info] }));
    const quiet = screen.getByRole("note", { name: "Risk diagnostics" });
    expect(quiet).not.toHaveAttribute("open");
    expect(within(quiet).getByText("2 informational notes")).toBeInTheDocument();
    unmount();

    renderPanel(
      envelope({
        risk_diagnostics: [
          { ...info, kind: "low_regression_r2", severity: "warning", message: "weak fit" },
          info
        ]
      })
    );
    const loud = screen.getByRole("note", { name: "Risk diagnostics" });
    expect(loud).toHaveAttribute("open");
    expect(within(loud).getByText("1 warning and 1 informational note")).toBeInTheDocument();
  });
});

describe("ScenarioReadout hero", () => {
  it("leads with the selected unit and keeps the other unit beside it", () => {
    const props = {
      result: result(),
      attributionMethod: "conditional_explicit" as const,
      factorMeta: {},
      currency: "USD"
    };
    const { rerender } = render(<ScenarioReadout {...props} showDollars nav={200_000} />);
    expect(screen.getByText("-$110,000")).toHaveClass("readout-hero-value", "down");
    expect(screen.getByText("-55.00% of the portfolio")).toBeInTheDocument();
    rerender(<ScenarioReadout {...props} showDollars={false} nav={200_000} />);
    expect(screen.getByText("-55.00%")).toHaveClass("readout-hero-value");
    expect(screen.getByText("-$110,000 on $200,000")).toBeInTheDocument();
    rerender(<ScenarioReadout {...props} showDollars={false} nav={null} />);
    expect(document.querySelector(".readout-hero-alt")).toBeNull();
  });
});
