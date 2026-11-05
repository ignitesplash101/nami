import { describe, expect, it } from "vitest";
import { buildEvidenceGauge, niceTicks } from "./charts";
import { buildHoldingImpactModel, buildTransmissionModel } from "./impact";
import type { ScenarioResult } from "./types";

function result(overrides: Partial<ScenarioResult> = {}): ScenarioResult {
  return {
    scenario_text: "tariffs",
    market_date: "2026-11-04",
    portfolio_key: "tech",
    portfolio_name: "Tech",
    portfolio_holdings: { AAPL: 0.5, NVDA: 0.3, MSFT: 0.2 },
    analogs_selected: [],
    factor_shocks: [
      { factor: "XLK", shock: -0.11, reasoning: "tech hardware hit" },
      { factor: "VIX", shock: 0.6, reasoning: "vol spike" },
      { factor: "GLD", shock: 0.085, reasoning: "haven bid" }
    ],
    periphery_shocks: [
      { ticker: "NVDA", shock: -0.08, reasoning: "China revenue" },
      { ticker: "AAPL", shock: -0.04, reasoning: "assembly footprint" }
    ],
    narrative: "",
    citations: [],
    factor_envelope: {
      XLK: { mean: -0.02, p10: -0.13, p90: 0.07, count: 4 },
      VIX: { mean: 0.36, p10: -0.13, p90: 0.95, count: 2 }
    },
    portfolio_pnl: {
      total_pnl: -0.101,
      by_factor_naive: { XLK: -0.07, VIX: 0.01, GLD: -0.001 },
      by_factor_conditional_shapley: null,
      by_factor_conditional_shapley_explicit: { XLK: -0.05, VIX: -0.03, GLD: 0.003, SPY: 0 },
      by_factor_conditional_shapley_grouped: null,
      by_ticker_factor: { AAPL: -0.05, NVDA: -0.02, MSFT: -0.006 },
      by_ticker_periphery: { AAPL: -0.02, NVDA: -0.004, MSFT: 0 },
      by_ticker_total: { AAPL: -0.07, NVDA: -0.024, MSFT: -0.006 }
    },
    narrative_shapley: null,
    adjustment_history: [],
    requested_as_of_date: null,
    narrative_mode: "grounded",
    selected_event_ids: [],
    analog_event_returns: [
      { event_id: "q4-2018", window_calendar_days: 91, factor_returns: { XLK: -0.178, VIX: 1.118, GLD: null } },
      { event_id: "tariffs-2025", window_calendar_days: 59, factor_returns: { XLK: 0.11, VIX: -0.147 } }
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

describe("buildTransmissionModel", () => {
  it("ranks factor and single-name rows by |contribution| from the main attribution map", () => {
    const model = buildTransmissionModel(result(), "conditional_explicit", undefined, EVENTS)!;
    expect(model.rows.map((row) => row.id)).toEqual([
      "factor:XLK",
      "factor:VIX",
      "single:AAPL",
      "single:NVDA",
      "factor:GLD"
    ]);
    // Unshocked factors with zero attribution are not drawn.
    expect(model.rows.some((row) => row.key === "SPY")).toBe(false);
    const xlk = model.rows[0];
    expect(xlk.shock).toBe(-0.11);
    expect(xlk.contribution).toBe(-0.05);
    expect(xlk.reasoning).toBe("tech hardware hit");
    expect(xlk.groupLabel).toBe("Sector");
    const aapl = model.rows.find((row) => row.key === "AAPL")!;
    expect(aapl).toMatchObject({ kind: "single-name", shock: -0.04, contribution: -0.02 });
  });

  it("reads the naive map when the result has no conditional attribution", () => {
    const model = buildTransmissionModel(result(), "naive")!;
    expect(model.rows.find((row) => row.key === "XLK")!.contribution).toBe(-0.07);
    expect(model.rows.find((row) => row.key === "VIX")!.contribution).toBe(0.01);
  });

  it("names each analog move, skips null returns, and keeps selection order", () => {
    const model = buildTransmissionModel(result(), "conditional_explicit", undefined, EVENTS)!;
    const xlk = model.rows.find((row) => row.key === "XLK")!;
    expect(xlk.analogs.map((analog) => [analog.name, analog.value])).toEqual([
      ["Q4 2018 trade war", -0.178],
      ["tariffs-2025", 0.11]
    ]);
    const gld = model.rows.find((row) => row.key === "GLD")!;
    expect(gld.analogs).toEqual([]);
    expect(model.analogCount).toBe(2);
  });

  it("draws the p10–p90 range only when at least 3 events cover the factor", () => {
    const model = buildTransmissionModel(result(), "conditional_explicit")!;
    const xlk = model.rows.find((row) => row.key === "XLK")!;
    expect(xlk.range).toMatchObject({ low: -0.13, high: 0.07, count: 4 });
    expect(xlk.range!.lowPct).toBeLessThan(xlk.range!.highPct);
    expect(model.rows.find((row) => row.key === "VIX")!.range).toBeNull();
  });

  it("places the shock, zero, and analogs on each row's own padded scale", () => {
    const xlk = buildTransmissionModel(result(), "conditional_explicit")!.rows.find(
      (row) => row.key === "XLK"
    )!;
    const [lowest, highest] = [xlk.analogs[0].pct, xlk.analogs[1].pct];
    expect(lowest).toBeGreaterThan(0);
    expect(highest).toBeLessThan(100);
    expect(xlk.strip.shockPct).toBeGreaterThan(lowest);
    expect(xlk.strip.shockPct).toBeLessThan(xlk.strip.zeroPct);
    expect(xlk.strip.zeroPct).toBeLessThan(highest);
  });

  it("flags a shock beyond every matched event, and stays quiet inside the range", () => {
    const beyond = result({
      factor_shocks: [{ factor: "XLK", shock: -0.3, reasoning: "" }]
    });
    expect(
      buildTransmissionModel(beyond, "conditional_explicit")!.rows.find((row) => row.key === "XLK")!
        .severity
    ).toBe("beyond");
    expect(
      buildTransmissionModel(result(), "conditional_explicit")!.rows.find(
        (row) => row.key === "XLK"
      )!.severity
    ).toBe("within");
  });

  it("gives history-less rows one shared strip scale so different shocks draw differently", () => {
    const model = buildTransmissionModel(result(), "conditional_explicit")!;
    const nvda = model.rows.find((row) => row.key === "NVDA")!;
    const aapl = model.rows.find((row) => row.key === "AAPL")!;
    expect(nvda.strip.zeroPct).toBeCloseTo(aapl.strip.zeroPct, 9);
    expect(nvda.strip.shockPct).toBeLessThan(aapl.strip.shockPct);
  });

  it("draws every effect bar from one shared zero, toward its sign", () => {
    const model = buildTransmissionModel(result(), "conditional_explicit")!;
    for (const row of model.rows) {
      if (row.contribution < 0) {
        expect(row.impact.leftPct + row.impact.widthPct).toBeCloseTo(model.impactZeroPct, 9);
      } else {
        expect(row.impact.leftPct).toBeCloseTo(model.impactZeroPct, 9);
      }
    }
    const xlk = model.rows.find((row) => row.key === "XLK")!;
    const vix = model.rows.find((row) => row.key === "VIX")!;
    expect(xlk.impact.widthPct).toBeGreaterThan(vix.impact.widthPct);
  });

  it("reconciles market drivers + company-specific to the total, surfacing any residual", () => {
    const model = buildTransmissionModel(result(), "conditional_explicit")!;
    expect(model.factorTotal).toBeCloseTo(-0.077, 9);
    expect(model.singleNameTotal).toBeCloseTo(-0.024, 9);
    expect(model.total).toBe(-0.101);
    expect(model.residual).toBe(0);

    const legacy = result();
    legacy.portfolio_pnl.total_pnl = -0.121;
    expect(buildTransmissionModel(legacy, "conditional_explicit")!.residual).toBeCloseTo(-0.02, 9);
  });

  it("fails closed on non-finite inputs", () => {
    const broken = result();
    broken.portfolio_pnl.by_factor_conditional_shapley_explicit!.XLK = Number.NaN;
    expect(buildTransmissionModel(broken, "conditional_explicit")).toBeNull();
    const badShock = result({ factor_shocks: [{ factor: "XLK", shock: Infinity, reasoning: "" }] });
    expect(buildTransmissionModel(badShock, "conditional_explicit")).toBeNull();
  });
});

describe("buildHoldingImpactModel", () => {
  it("ranks holdings by |effect| with their own modeled move and company-specific share", () => {
    const model = buildHoldingImpactModel(result())!;
    expect(model.rows.map((row) => row.ticker)).toEqual(["AAPL", "NVDA", "MSFT"]);
    const aapl = model.rows[0];
    expect(aapl.ownMove).toBeCloseTo(-0.14, 9);
    expect(aapl.singleNameSharePct).toBeCloseTo((0.02 / 0.07) * 100, 9);
    expect(model.rows.find((row) => row.ticker === "MSFT")!.singleNameSharePct).toBe(0);
    expect(aapl.bar.leftPct + aapl.bar.widthPct).toBeCloseTo(model.zeroPct, 9);
  });

  it("does not draw an opposite-signed company-specific part inside the bar", () => {
    const mixed = result();
    mixed.portfolio_pnl.by_ticker_periphery.AAPL = 0.01;
    mixed.portfolio_pnl.by_ticker_total.AAPL = -0.04;
    const aapl = buildHoldingImpactModel(mixed)!.rows.find((row) => row.ticker === "AAPL")!;
    expect(aapl.singleNameSharePct).toBe(0);
  });

  it("fails closed on non-finite totals and reports no move for a zero weight", () => {
    const broken = result();
    broken.portfolio_pnl.by_ticker_total.AAPL = Number.NaN;
    expect(buildHoldingImpactModel(broken)).toBeNull();
    const zero = result();
    zero.portfolio_holdings.MSFT = 0;
    expect(buildHoldingImpactModel(zero)!.rows.find((row) => row.ticker === "MSFT")!.ownMove).toBeNull();
  });
});

describe("niceTicks + evidence axis", () => {
  it("steps by 1/2/2.5/5 × 10^k inside the domain", () => {
    expect(niceTicks(-0.32, 0.11, 5)).toEqual([-0.3, -0.2, -0.1, 0, 0.1]);
    expect(niceTicks(0, 1, 4)).toEqual([0, 0.25, 0.5, 0.75, 1]);
    expect(niceTicks(1, 1)).toEqual([]);
  });

  it("anchors zero on the evidence axis and positions every replayed event", () => {
    const withEvidence = result({
      pnl_uncertainty: { band_1sigma: 0.01, portfolio_idio_vol_weekly: 0.005, horizon_weeks: 4 },
      analog_replay: {
        per_event: [
          { event_id: "a", replay_pnl: -0.19, n_factors_covered: 26, n_factors_total: 26 },
          { event_id: "b", replay_pnl: -0.12, n_factors_covered: 26, n_factors_total: 26 }
        ],
        min_pnl: -0.19,
        median_pnl: -0.155,
        max_pnl: -0.12
      }
    });
    const gauge = buildEvidenceGauge(withEvidence)!;
    // Every layer is a loss, yet zero is still on the axis — to the right of them all.
    expect(gauge.zero.pct).toBeGreaterThan(gauge.idio!.highPct);
    expect(gauge.zero.pct).toBeLessThanOrEqual(100);
    expect(gauge.replay!.events.map((event) => event.eventId)).toEqual(["a", "b"]);
    expect(gauge.replay!.events[0].pct).toBeCloseTo(gauge.replay!.minPct, 9);
    expect(gauge.ticks.some((tick) => tick.value === 0)).toBe(true);
  });
});
