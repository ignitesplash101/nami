import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ResultsPanel } from "./results/ResultsPanel";
import type { ScenarioResult, ScenarioRunResponse } from "./types";

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

function renderResults() {
  const setValuationSort = vi.fn();
  render(
    <ResultsPanel
      envelope={envelopeFixture()}
      attributionMethod="naive"
      setAttributionMethod={() => {}}
      factorMeta={{}}
      displayMode="pct"
      setDisplayMode={() => {}}
      navInput="100000"
      setNavInput={() => {}}
      valuationSort={{ key: "delta", dir: "asc" }}
      setValuationSort={setValuationSort}
      canDecompose={false}
      isDecomposing={false}
      decomposeProgress={null}
      onDecompose={() => {}}
      onOpenMethodology={() => {}}
      canSave={false}
      onSave={() => {}}
    />
  );
  return { setValuationSort };
}

describe("numeric table system", () => {
  it("right-aligns numeric columns via th.num/td.num in the factor shocks table", () => {
    renderResults();
    const header = screen.getByText("P&L contrib").closest("th");
    expect(header).toHaveClass("num");
    // "-6.00%" appears in several tables (factor contrib, name-level total) —
    // every numeric occurrence must sit in a td.num cell.
    const cells = screen.getAllByText("-6.00%").map((el) => el.closest("td"));
    expect(cells.length).toBeGreaterThan(0);
    for (const cell of cells) {
      expect(cell).toHaveClass("num");
    }
  });

  it("exposes aria-sort on valuation headers and toggles via SortableTh", () => {
    const { setValuationSort } = renderResults();
    // The valuation table lives in the Positions sub-tab (hidden by default).
    fireEvent.click(screen.getByRole("tab", { name: "Positions" }));
    const deltaHeader = screen.getByRole("button", { name: /Δ\$/ }).closest("th");
    expect(deltaHeader).toHaveAttribute("aria-sort", "ascending");
    expect(deltaHeader).toHaveClass("sortable", "num");

    screen.getByRole("button", { name: "Value" }).click();
    expect(setValuationSort).toHaveBeenCalledWith({ key: "value", dir: "desc" });
  });

  it("wraps every results table in table-wrap for the anchored scroll fade", () => {
    const { container } = render(
      <ResultsPanel
        envelope={envelopeFixture()}
        attributionMethod="naive"
        setAttributionMethod={() => {}}
        factorMeta={{}}
        displayMode="pct"
        setDisplayMode={() => {}}
        navInput="100000"
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
    // Factor shocks, name-level, analogs (TableCard) + valuation table.
    expect(container.querySelectorAll(".table-wrap > .table-scroll").length).toBeGreaterThanOrEqual(
      4
    );
  });
});
