import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { EvidenceBlock } from "./EvidenceBlock";
import type { ScenarioResult } from "./types";
import { closeExpandedCard } from "./useFullscreen";

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

afterEach(() => {
  // Reset expanded-card globals so a failing hook-order run can't poison
  // later tests (the whole point of that test is that a broken component
  // LEAKS these).
  closeExpandedCard();
  document.body.style.overflow = "";
  document.documentElement.classList.remove("has-expanded-card");
});

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

  it("hook-order guard: expanded state and scroll-lock cleanup survive a same-instance gauge flip", () => {
    // A fresh mount with a null gauge can NEVER catch hooks placed below
    // `if (!gauge) return null` — the first render just returns before
    // reaching them. The regression only manifests when the SAME fiber
    // re-renders across a gauge-truthiness flip. And it does so SILENTLY:
    // React's "Rendered fewer hooks than expected" check needs at least one
    // hook consumed in the re-render, so a pre-hook early return (zero hooks)
    // slips past it — verified empirically — and instead wipes the fiber's
    // hook state and orphans the effect cleanups. So this test asserts the
    // observable damage, not a throw: (1) the expanded-card state must
    // survive a truthy → null → truthy flip; (2) unmount must release the
    // scroll-lock (orphaned cleanups would leak it forever).
    const withGauge = makeResult();
    const withoutGauge = makeResult({
      severity_ladder: null,
      pnl_uncertainty: null,
      analog_replay: null
    });
    const props = { analogEvents: EVENTS, showDollars: false, nav: null, currency: "USD" };
    const { rerender, unmount, container } = render(<EvidenceBlock result={withGauge} {...props} />);

    // Expand (jsdom has no native Fullscreen API → the expanded-card fallback).
    fireEvent.click(screen.getByRole("button", { name: "Expand evidence and bounds" }));
    expect(document.body.style.overflow).toBe("hidden");
    expect(document.documentElement.classList.contains("has-expanded-card")).toBe(true);

    // Same instance: gauge flips null (a thin payload) and back.
    expect(() => rerender(<EvidenceBlock result={withoutGauge} {...props} />)).not.toThrow();
    expect(container).toBeEmptyDOMElement();
    expect(() => rerender(<EvidenceBlock result={withGauge} {...props} />)).not.toThrow();

    // Hook state survived the flip: the controller still reports expanded.
    // (Hooks below the early return reset it — the label would read Expand.)
    expect(screen.getByRole("button", { name: "Collapse evidence and bounds" })).toBeInTheDocument();

    // Unmount releases the scroll-lock; orphaned effect cleanups would leak it.
    unmount();
    expect(document.body.style.overflow).toBe("");
    expect(document.documentElement.classList.contains("has-expanded-card")).toBe(false);
  });

  it("carries the fullscreen affordance next to the eyebrow when it renders", () => {
    render(
      <EvidenceBlock
        result={makeResult()}
        analogEvents={EVENTS}
        showDollars={false}
        nav={null}
        currency="USD"
      />
    );
    expect(
      screen.getByRole("button", { name: "Expand evidence and bounds" })
    ).toBeInTheDocument();
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
