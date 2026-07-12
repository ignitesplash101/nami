import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MethodologyDiagnostics } from "./MethodologyDiagnostics";
import type { ScenarioResult } from "../types";

vi.mock("../PlotLazy", () => ({
  PlotLazy: () => <div data-testid="plot" />
}));

function resultFixture(): ScenarioResult {
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
      by_factor_naive: { SPY: -0.06 },
      by_factor_conditional_shapley: { SPY: -0.05, GLD: -0.01 },
      by_factor_conditional_shapley_explicit: { SPY: -0.06 },
      by_factor_conditional_shapley_grouped: { SPY: -0.06 },
      by_ticker_factor: { AAPL: -0.06 },
      by_ticker_periphery: { AAPL: -0.02 },
      by_ticker_total: { AAPL: -0.08 }
    },
    narrative_shapley: null,
    adjustment_history: [],
    requested_as_of_date: null,
    narrative_mode: "grounded",
    selected_event_ids: []
  };
}

describe("MethodologyDiagnostics", () => {
  it("offers the three audit views with naive as the default", () => {
    render(<MethodologyDiagnostics result={resultFixture()} factorMeta={{}} />);
    expect(screen.getByText("Methodology diagnostics")).toBeInTheDocument();
    expect(
      screen.getByText("Audit views — same total, different credit-splitting rules.")
    ).toBeInTheDocument();
    const naive = screen.getByRole("radio", { name: "Naive algebra" });
    expect(naive).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Full conditional" })).toBeEnabled();
    expect(screen.getByRole("radio", { name: "Grouped (full conditional)" })).toBeEnabled();
    // naive caveat renders by default
    expect(screen.getByText(/assumes factor independence/)).toBeInTheDocument();
  });

  it("keeps the correlation-credit caveat VERBATIM on the full-conditional view", () => {
    render(<MethodologyDiagnostics result={resultFixture()} factorMeta={{}} />);
    fireEvent.click(screen.getByRole("radio", { name: "Full conditional" }));
    expect(
      screen.getByText(
        /Correlation credit, non-causal\. Unshocked factors can receive positive or negative/
      )
    ).toBeInTheDocument();
  });

  it("disables conditional views when the maps are absent (old payloads)", () => {
    const result = resultFixture();
    result.portfolio_pnl.by_factor_conditional_shapley = null;
    result.portfolio_pnl.by_factor_conditional_shapley_grouped = null;
    render(<MethodologyDiagnostics result={result} factorMeta={{}} />);
    expect(screen.getByRole("radio", { name: "Full conditional" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Grouped (full conditional)" })).toBeDisabled();
  });
});
