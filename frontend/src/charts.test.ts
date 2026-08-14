import { describe, expect, it } from "vitest";
import {
  buildAnalogReplayRows,
  buildBookProfileRows,
  buildEvidenceGauge,
  buildPositionValuations,
  summarizeFactorTable,
  summarizeNameTable,
  buildReadout,
  buildWaterfallData,
  buildWaterfallDataDollars,
  selectMainAttribution,
  factorReasoningRows,
  formatCurrency,
  formatSignedCurrency,
  parseNav,
  topContributor
} from "./charts";
import type { ScenarioResult } from "./types";

function fixtureResult(): ScenarioResult {
  return {
    scenario_text: "risk-off",
    market_date: "2026-05-25",
    portfolio_key: "sample",
    portfolio_name: "Sample",
    portfolio_holdings: { AAPL: 0.6, MSFT: 0.4 },
    analogs_selected: [],
    factor_shocks: [{ factor: "SPY", shock: -0.1, reasoning: "broad selloff" }],
    periphery_shocks: [],
    narrative: "mock",
    citations: [],
    factor_envelope: {},
    portfolio_pnl: {
      total_pnl: -0.08,
      by_factor_naive: { SPY: -0.06, VIX: 0 },
      by_factor_conditional_shapley: { SPY: -0.04, ACWI: -0.02 },
      by_factor_conditional_shapley_explicit: { SPY: -0.06, ACWI: 0 },
      by_factor_conditional_shapley_grouped: { SPY: -0.06, ACWI: 0 },
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

describe("chart data helpers", () => {
  it("builds a waterfall with periphery and total bars", () => {
    const result = fixtureResult();
    result.portfolio_pnl.by_ticker_periphery = { AAPL: -0.0001, MSFT: 0 };
    const data = buildWaterfallData(result, "naive");

    expect(data.bars.map((bar) => bar.shortLabel)).toContain("US large-cap (SPY)");
    expect(data.bars.map((bar) => bar.shortLabel)).toContain("Periphery");
    expect(data.bars.at(-1)).toMatchObject({
      id: "total",
      shortLabel: "Total",
      kind: "total",
      value: -0.08,
      start: 0,
      end: -0.08
    });
    expect(data.unit).toEqual({ kind: "percent" });
  });

  it("omits the periphery waterfall bar when idiosyncratic contribution is zero", () => {
    const result = fixtureResult();
    result.portfolio_pnl.by_ticker_periphery = { AAPL: 0, MSFT: 0 };
    const data = buildWaterfallData(result, "naive");

    expect(data.bars.map((bar) => bar.shortLabel)).not.toContain("Periphery");
    expect(data.bars.at(-1)?.shortLabel).toBe("Total");
  });

  it("omits visually zero non-material periphery from the waterfall", () => {
    const result = fixtureResult();
    result.portfolio_pnl.by_ticker_periphery = { AAPL: 0.000004, MSFT: 0 };
    const data = buildWaterfallData(result, "naive");

    expect(data.bars.map((bar) => bar.shortLabel)).not.toContain("Periphery");
    expect(data.bars.at(-1)?.shortLabel).toBe("Total");
  });

  it("switches top contributor under conditional attribution", () => {
    const naive = topContributor(fixtureResult(), "naive");
    const conditional = topContributor(fixtureResult(), "conditional");

    expect(naive.factor).toBe("SPY");
    expect(conditional.factor).toBe("SPY");
    expect(conditional.contribution).toBe(-0.04);
  });

  it("labels correlation-only rows when conditional Shapley attributes unshocked factors", () => {
    const rows = factorReasoningRows(fixtureResult(), "conditional");
    const acwi = rows.find((row) => row.factor === "ACWI");

    expect(acwi?.shockApplied).toBe(0);
    expect(acwi?.reasoning).toContain("Correlation credit; no explicit shock");
    expect(acwi?.factorLabel).toBe("Global equities (ACWI)");
  });

  it("explicit-only mode picks the explicit-only attribution and suppresses correlation-only label", () => {
    const top = topContributor(fixtureResult(), "conditional_explicit");
    expect(top.factor).toBe("SPY");
    expect(top.contribution).toBe(-0.06);

    // ACWI should not appear as a row at all in explicit-only — it has zero
    // contribution AND no explicit shock, so the row filter drops it.
    const rows = factorReasoningRows(fixtureResult(), "conditional_explicit");
    const acwi = rows.find((row) => row.factor === "ACWI");
    expect(acwi).toBeUndefined();
  });

  it("grouped mode reads from the grouped attribution map", () => {
    const top = topContributor(fixtureResult(), "conditional_grouped");
    expect(top.factor).toBe("SPY");
    expect(top.contribution).toBe(-0.06);
  });

  it("grouped waterfall displays group totals instead of redistributed factor bars", () => {
    const result = fixtureResult();
    result.portfolio_pnl.by_factor_conditional_shapley_grouped = {
      SPY: -0.03,
      ACWI: -0.01,
      XLK: -0.02,
      VIX: 0.01
    };
    result.portfolio_pnl.by_ticker_periphery = { AAPL: 0, MSFT: 0 };

    const data = buildWaterfallData(result, "conditional_grouped");

    const bars = new Map(data.bars.map((bar) => [bar.shortLabel, bar]));
    expect([...bars.keys()]).toContain("Market");
    expect([...bars.keys()]).toContain("Sector");
    expect([...bars.keys()]).toContain("Macro");
    expect([...bars.keys()]).not.toContain("US large-cap (SPY)");
    expect(bars.get("Market")?.value).toBeCloseTo(-0.04);
    expect(bars.get("Sector")?.value).toBeCloseTo(-0.02);
    expect(bars.get("Macro")?.value).toBeCloseTo(0.01);
  });

  it("explodes material periphery into signed ticker bars", () => {
    const data = buildWaterfallData(fixtureResult(), "naive");

    const bars = new Map(data.bars.map((bar) => [bar.shortLabel, bar]));
    expect([...bars.keys()]).toContain("AAPL periphery");
    expect([...bars.keys()]).not.toContain("Periphery");
    expect(bars.get("AAPL periphery")?.value).toBeCloseTo(-0.02);
  });

  it("does not hide offsetting material periphery behind a zero net bar", () => {
    const result = fixtureResult();
    result.portfolio_pnl.total_pnl = -0.06;
    result.portfolio_pnl.by_ticker_periphery = { AAPL: 0.01, MSFT: -0.01 };

    const data = buildWaterfallData(result, "naive");

    const bars = new Map(data.bars.map((bar) => [bar.shortLabel, bar]));
    expect([...bars.keys()]).toContain("AAPL periphery");
    expect([...bars.keys()]).toContain("MSFT periphery");
    expect([...bars.keys()]).not.toContain("Periphery");
    expect(bars.get("AAPL periphery")?.value).toBeCloseTo(0.01);
    expect(bars.get("MSFT periphery")?.value).toBeCloseTo(-0.01);
  });

  it("keeps the top three periphery names and rolls the rest into other periphery", () => {
    const result = fixtureResult();
    result.portfolio_holdings = {
      AAPL: 0.3,
      MSFT: 0.25,
      NVDA: 0.2,
      AMZN: 0.15,
      GOOGL: 0.1
    };
    result.portfolio_pnl.total_pnl = -0.063;
    result.portfolio_pnl.by_ticker_periphery = {
      AAPL: -0.005,
      MSFT: 0.004,
      NVDA: -0.003,
      AMZN: 0.002,
      GOOGL: -0.001
    };

    const data = buildWaterfallData(result, "naive");

    const bars = new Map(data.bars.map((bar) => [bar.shortLabel, bar]));
    expect([...bars.keys()]).toContain("AAPL periphery");
    expect([...bars.keys()]).toContain("MSFT periphery");
    expect([...bars.keys()]).toContain("NVDA periphery");
    expect([...bars.keys()]).toContain("Other periphery");
    expect([...bars.keys()]).not.toContain("AMZN periphery");
    expect([...bars.keys()]).not.toContain("GOOGL periphery");
    expect(bars.get("Other periphery")?.value).toBeCloseTo(0.001);
  });

  it("builds mixed-sign cumulative geometry from the ordered contribution steps", () => {
    const result = fixtureResult();
    result.portfolio_pnl.by_factor_naive = { SPY: -0.06, XLK: 0.04, TNX: 0.01 };
    result.portfolio_pnl.by_ticker_periphery = { AAPL: 0, MSFT: 0 };
    result.portfolio_pnl.total_pnl = -0.01;

    const contributions = buildWaterfallData(result, "naive").bars.filter(
      (bar) => bar.kind !== "total"
    );

    expect(contributions[0]).toMatchObject({ value: -0.06, start: 0, end: -0.06 });
    expect(contributions[1]).toMatchObject({ value: 0.04, start: -0.06 });
    expect(contributions[1].end).toBeCloseTo(-0.02);
    expect(contributions[2].start).toBeCloseTo(-0.02);
    expect(contributions[2].end).toBeCloseTo(-0.01);
  });

  it("caps contribution steps by aggregating excess factors without hiding material periphery", () => {
    const result = fixtureResult();
    result.portfolio_pnl.by_factor_naive = {
      F1: -0.09,
      F2: 0.08,
      F3: -0.07,
      F4: 0.06,
      F5: -0.05,
      F6: 0.04,
      F7: -0.03,
      F8: 0.02
    };
    result.portfolio_pnl.by_ticker_periphery = {
      AAPL: -0.005,
      MSFT: 0.004,
      NVDA: -0.003,
      AMZN: 0.002
    };
    result.portfolio_pnl.total_pnl = -0.042;

    const data = buildWaterfallData(result, "naive", undefined, "factor", 6);
    const contributionBars = data.bars.filter(
      (bar) => bar.kind !== "total" && bar.kind !== "residual"
    );

    expect(contributionBars).toHaveLength(6);
    expect(contributionBars.filter((bar) => bar.kind === "factor")).toHaveLength(1);
    expect(contributionBars.find((bar) => bar.shortLabel === "Other factors")?.value).toBeCloseTo(
      0.05
    );
    expect(contributionBars.map((bar) => bar.shortLabel)).toEqual(
      expect.arrayContaining([
        "AAPL periphery",
        "MSFT periphery",
        "NVDA periphery",
        "Other periphery"
      ])
    );
  });

  it("adds an explicit residual step when legacy contributions do not reconcile", () => {
    const result = fixtureResult();
    result.portfolio_pnl.by_factor_naive = { SPY: -0.06 };
    result.portfolio_pnl.by_ticker_periphery = { AAPL: 0, MSFT: 0 };
    result.portfolio_pnl.total_pnl = -0.08;

    const residual = buildWaterfallData(result, "naive").bars.find(
      (bar) => bar.kind === "residual"
    );

    expect(residual).toMatchObject({
      id: "residual",
      shortLabel: "Residual",
      start: -0.06,
      end: -0.08,
      formattedValue: "-2.00%"
    });
    expect(residual?.value).toBeCloseTo(-0.02);
  });

  it("fails closed when chart inputs contain a non-finite number", () => {
    const result = fixtureResult();
    result.portfolio_pnl.by_factor_naive = { SPY: Number.NaN };

    expect(buildWaterfallData(result, "naive")).toEqual({
      bars: [],
      unit: { kind: "percent" }
    });
  });

  it("preserves long and short factor labels in the semantic bars", () => {
    const data = buildWaterfallData(fixtureResult(), "naive");
    expect(data.bars[0]).toMatchObject({
      id: "factor:SPY",
      shortLabel: "US large-cap (SPY)",
      fullLabel: "US large-cap equities (SPY)"
    });
  });

  it("builds an answer-first readout with direction, headline, and evidence", () => {
    const readout = buildReadout(fixtureResult(), "naive");
    expect(readout.direction).toBe("loss");
    expect(readout.topFactor).toBe("US large-cap equities (SPY)");
    expect(readout.headline).toContain("loses");
    expect(readout.headline).toContain("SPY");
    expect(readout.analogCount).toBe(0);
    expect(readout.citationCount).toBe(0);
  });

  it("flags a roughly-flat result as flat", () => {
    const result = fixtureResult();
    result.portfolio_pnl.total_pnl = 0.0001;
    const readout = buildReadout(result, "naive");
    expect(readout.direction).toBe("flat");
    expect(readout.headline).toContain("flat");
  });
});

describe("buildReadout idio band", () => {
  it("is null when the result carries no uncertainty block (old payloads)", () => {
    expect(buildReadout(fixtureResult(), "naive").idioBand).toBeNull();
  });

  it("carries the ±1σ band when present", () => {
    const result = fixtureResult();
    result.pnl_uncertainty = {
      band_1sigma: 0.021,
      portfolio_idio_vol_weekly: 0.0089,
      horizon_weeks: 5.64
    };
    expect(buildReadout(result, "naive").idioBand).toBeCloseTo(0.021, 10);
  });
});

describe("buildAnalogReplayRows", () => {
  it("returns null when the result carries no replay block (old payloads)", () => {
    expect(buildAnalogReplayRows(fixtureResult(), {})).toBeNull();
  });

  it("maps replay entries to rows in selection order, naming events when known", () => {
    const result = fixtureResult();
    result.analog_replay = {
      per_event: [
        {
          event_id: "covid-crash-2020",
          replay_pnl: -0.21,
          n_factors_covered: 22,
          n_factors_total: 22
        },
        {
          event_id: "lehman-gfc-2008",
          replay_pnl: -0.34,
          n_factors_covered: 17,
          n_factors_total: 22
        }
      ],
      min_pnl: -0.34,
      median_pnl: -0.275,
      max_pnl: -0.21
    };

    const rows = buildAnalogReplayRows(result, {
      "covid-crash-2020": {
        event_id: "covid-crash-2020",
        name: "COVID-19 crash",
        start_date: "2020-02-19",
        end_date: "2020-03-23",
        tags: ["pandemic"],
        description: ""
      }
    });

    expect(rows).not.toBeNull();
    expect(rows![0]).toEqual({
      eventId: "covid-crash-2020",
      name: "COVID-19 crash",
      pnl: -0.21,
      covered: 22,
      total: 22
    });
    // Unknown event ids fall back to the raw id (saved payloads without a snapshot).
    expect(rows![1].name).toBe("lehman-gfc-2008");
  });

  it("returns null for an empty per_event list and tolerates a null events map", () => {
    const result = fixtureResult();
    result.analog_replay = { per_event: [], min_pnl: 0, median_pnl: 0, max_pnl: 0 };
    expect(buildAnalogReplayRows(result, null)).toBeNull();
  });
});

describe("currency formatting + dollar waterfall (MTM)", () => {
  it("formats USD with no fractional cents by default", () => {
    expect(formatCurrency(1284500, "USD")).toBe("$1,284,500");
  });

  it("signs dollar P&L", () => {
    expect(formatSignedCurrency(12340, "USD")).toBe("+$12,340");
    expect(formatSignedCurrency(-5400, "USD")).toBe("-$5,400");
  });

  it("does not throw on an unknown currency code", () => {
    expect(formatCurrency(1000, "ZZZ")).toContain("1,000");
  });

  it("scales the waterfall by NAV for the dollar view", () => {
    const nav = 1_000_000;
    const pct = buildWaterfallData(fixtureResult(), "naive");
    const usd = buildWaterfallDataDollars(fixtureResult(), "naive", nav, "USD");
    expect(usd.bars.map((bar) => bar.id)).toEqual(pct.bars.map((bar) => bar.id));
    expect(usd.bars.at(-1)?.value).toBeCloseTo(-0.08 * nav);
    expect(usd.bars.at(-1)?.formattedValue).toBe("-$80,000");
    expect(usd.unit).toEqual({ kind: "currency", currency: "USD" });
  });

  it("uses exact signed labels in both percent and currency modes", () => {
    const result = fixtureResult();
    result.portfolio_pnl.by_factor_naive = { SPY: 0.01234 };
    result.portfolio_pnl.by_ticker_periphery = { AAPL: 0, MSFT: 0 };
    result.portfolio_pnl.total_pnl = 0.01234;

    expect(buildWaterfallData(result, "naive").bars[0].formattedValue).toBe("+1.23%");
    expect(
      buildWaterfallDataDollars(result, "naive", 1_000_000, "USD").bars[0].formattedValue
    ).toBe("+$12,340");
  });

  it("fails closed for an invalid dollar scale", () => {
    expect(buildWaterfallDataDollars(fixtureResult(), "naive", Number.NaN).bars).toEqual([]);
  });
});

describe("parseNav", () => {
  it("parses plain, $, commas, and k/m/b suffixes", () => {
    expect(parseNav("1000000")).toBe(1_000_000);
    expect(parseNav("$1,000,000")).toBe(1_000_000);
    expect(parseNav("1m")).toBe(1_000_000);
    expect(parseNav("250k")).toBe(250_000);
    expect(parseNav("2.5b")).toBe(2_500_000_000);
    expect(parseNav("  $250,000 ")).toBe(250_000);
  });

  it("rejects junk / empty / non-positive (no silent NaN)", () => {
    expect(parseNav("")).toBeNull();
    expect(parseNav("abc")).toBeNull();
    expect(parseNav("1x")).toBeNull();
    expect(parseNav("0")).toBeNull();
    expect(parseNav("-5")).toBeNull();
  });
});

describe("buildPositionValuations", () => {
  it("scales weight×NAV when unmarked; stressed = value + delta; deltaPct = delta/value", () => {
    const rows = buildPositionValuations(fixtureResult(), 1_000_000);
    const aapl = rows.find((r) => r.ticker === "AAPL");
    expect(aapl).toBeDefined();
    expect(aapl?.value).toBeCloseTo(0.6 * 1_000_000); // weight × NAV
    expect(aapl?.delta).toBeCloseTo(1_000_000 * -0.06); // NAV × by_ticker_total
    expect(aapl?.stressed).toBeCloseTo((aapl?.value ?? 0) + (aapl?.delta ?? 0));
    expect(aapl?.deltaPct).toBeCloseTo((aapl?.delta ?? 0) / (aapl?.value ?? 1));
  });
});

describe("buildBookProfileRows", () => {
  it("sorts by absolute exposure, labels via the lookup, and truncates", () => {
    const rows = buildBookProfileRows(
      { SPY: 0.4, GLD: -0.9, HYG: 0.1, ACWI: 0.5 },
      (key) => `L:${key}`,
      3
    );
    expect(rows.map((r) => r.key)).toEqual(["GLD", "ACWI", "SPY"]);
    expect(rows[0]).toEqual({ key: "GLD", label: "L:GLD", exposure: -0.9 });
  });
});

describe("evidence gauge + drill summaries", () => {
  it("positions every layer on a shared padded axis", () => {
    const result = fixtureResult();
    result.pnl_uncertainty = { band_1sigma: 0.01, portfolio_idio_vol_weekly: 0.005, horizon_weeks: 4 };
    result.severity_ladder = { worst_pnl: -0.15, base_pnl: -0.08, best_pnl: -0.02, n_banded: 2, n_held: 0 };
    result.analog_replay = {
      per_event: [
        { event_id: "a", replay_pnl: -0.19, n_factors_covered: 26, n_factors_total: 26 },
        { event_id: "b", replay_pnl: -0.12, n_factors_covered: 26, n_factors_total: 26 }
      ],
      min_pnl: -0.19,
      median_pnl: -0.155,
      max_pnl: -0.12
    };
    const gauge = buildEvidenceGauge(result);
    expect(gauge).not.toBeNull();
    // domain spans [-0.19, -0.02] padded: replay min is leftmost, ladder best rightmost
    expect(gauge!.replay!.minPct).toBeLessThan(gauge!.ladder!.lowPct + 1e-9);
    expect(gauge!.ladder!.highPct).toBeGreaterThan(gauge!.base.pct);
    expect(gauge!.base.pct).toBeGreaterThan(0);
    expect(gauge!.base.pct).toBeLessThan(100);
    expect(gauge!.idio!.lowPct).toBeLessThan(gauge!.base.pct);
    expect(gauge!.idio!.highPct).toBeGreaterThan(gauge!.base.pct);
  });

  it("returns null when no evidence layer exists (very old payloads)", () => {
    const result = fixtureResult();
    expect(buildEvidenceGauge(result)).toBeNull();
  });

  it("summarizes the factor and name tables", () => {
    const result = fixtureResult();
    expect(summarizeFactorTable(result)).toContain("1 factor shocked");
    expect(summarizeFactorTable(result)).toContain("-10.00%");
    expect(summarizeNameTable(result)).toBe("2 holdings · worst AAPL -6.00%");
  });
});

describe("one methodology, two zooms (Phase 31i)", () => {
  it("group zoom rolls up the SAME explicit map — both zooms sum to the same factor P&L", () => {
    const result = fixtureResult();
    result.portfolio_pnl.by_ticker_periphery = { AAPL: 0, MSFT: 0 };
    result.portfolio_pnl.by_factor_conditional_shapley_explicit = {
      SPY: -0.05, // market
      XLK: -0.03, // sector
      TNX: 0.01 // macro
    };
    result.portfolio_pnl.total_pnl = -0.07;
    const sumFactorBars = (data: ReturnType<typeof buildWaterfallData>) =>
      data.bars
        .filter((bar) => bar.kind === "factor" || bar.kind === "aggregate")
        .reduce((sum, bar) => sum + bar.value, 0);

    const byFactor = buildWaterfallData(result, "conditional_explicit", undefined, "factor");
    const byGroup = buildWaterfallData(result, "conditional_explicit", undefined, "group");

    expect(sumFactorBars(byGroup)).toBeCloseTo(sumFactorBars(byFactor), 12);
    expect(sumFactorBars(byGroup)).toBeCloseTo(-0.07, 12);
    // groups render in the canonical order, built from the same numbers
    expect(byGroup.bars.slice(0, -1).map((bar) => bar.shortLabel)).toEqual([
      "Market",
      "Sector",
      "Macro"
    ]);
  });

  it("selectMainAttribution prefers explicit and flags the naive fallback as degraded", () => {
    const result = fixtureResult();
    expect(selectMainAttribution(result)).toEqual({
      method: "conditional_explicit",
      degraded: false
    });
    result.portfolio_pnl.by_factor_conditional_shapley_explicit = null;
    expect(selectMainAttribution(result)).toEqual({ method: "naive", degraded: true });
  });
});
