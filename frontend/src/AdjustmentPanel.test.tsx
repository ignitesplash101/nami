import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdjustmentPanel } from "./AdjustmentPanel";
import { ApiError } from "./api";
import { ToastProvider } from "./toast";
import type { ScenarioResult, ScenarioRunResponse } from "./types";

const adjustMock = vi.fn<() => Promise<ScenarioRunResponse>>();

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    adjustScenarioShocks: () => adjustMock()
  };
});

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
    factor_envelope: { SPY: { mean: -0.05, p10: -0.2, p90: 0.05, count: 4 } },
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
    requested_as_of_date: null,
    narrative_mode: "grounded",
    selected_event_ids: []
  };
}

function envelopeFixture(): ScenarioRunResponse {
  return {
    result: resultFixture(),
    analog_events: {},
    cache_key: "cache-key-1",
    reproducibility: null
  };
}

function renderPanel(overrides: { prefillRerun?: (text: string) => void } = {}) {
  const prefillRerun = overrides.prefillRerun ?? vi.fn();
  render(
    <ToastProvider>
      <AdjustmentPanel
        envelope={envelopeFixture()}
        canonicalSnapshot={resultFixture()}
        factorMeta={{}}
        onResult={() => {}}
        prefillRerun={prefillRerun}
      />
    </ToastProvider>
  );
  return { prefillRerun };
}

// Braces matter: a FUNCTION returned from beforeEach is registered by vitest as
// a teardown callback — `mockReset()` returns the (callable) mock, which would
// then be invoked at cleanup and leave an unhandled rejected promise.
beforeEach(() => {
  adjustMock.mockReset();
});

describe("AdjustmentPanel error dispatch", () => {
  it("classifies rerun_required via the error kind, not the detail text", async () => {
    // Detail deliberately lacks the word "rerun" — the old regex would miss it.
    adjustMock.mockRejectedValue(
      new ApiError({
        status: 422,
        detail: "That asks for a new transmission mechanism.",
        kind: "rerun_required"
      })
    );
    renderPanel();
    fireEvent.change(screen.getByLabelText("Describe an adjustment"), {
      target: { value: "add an oil shock" }
    });
    fireEvent.click(screen.getByText("Apply adjustment"));

    await waitFor(() =>
      expect(screen.getByText("That asks for a new transmission mechanism.")).toBeInTheDocument()
    );
    expect(screen.getByText("Pre-fill rerun in Scenario panel")).toBeInTheDocument();
  });

  it("offers a re-run CTA when the cache entry has expired (410)", async () => {
    adjustMock.mockRejectedValue(
      new ApiError({
        status: 410,
        detail: "Scenario result not found for cache_key='gone'.",
        kind: "expired"
      })
    );
    const prefillRerun = vi.fn();
    renderPanel({ prefillRerun });
    fireEvent.click(screen.getByText("Recalculate P&L"));

    const cta = await screen.findByText("Re-run scenario");
    fireEvent.click(cta);
    expect(prefillRerun).toHaveBeenCalledWith("Risk-off shock");
  });

  it("pushes a success toast when an adjustment applies", async () => {
    adjustMock.mockResolvedValue(envelopeFixture());
    renderPanel();
    fireEvent.click(screen.getByText("Recalculate P&L"));
    await screen.findByText("Adjustment applied.");
  });
});
