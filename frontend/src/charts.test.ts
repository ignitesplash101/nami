import { afterEach, describe, expect, it } from "vitest";
import {
  buildAnalogReplayRows,
  buildBookProfileRows,
  buildPositionValuations,
  buildReadout,
  buildWaterfallData,
  buildWaterfallDataDollars,
  chartTheme,
  factorReasoningRows,
  formatCurrency,
  formatSignedCurrency,
  parseNav,
  resetChartThemeForTests,
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

    expect(data.x).toContain("US large-cap (SPY)");
    expect(data.x).toContain("Periphery");
    expect(data.x[data.x.length - 1]).toBe("Total");
    expect(data.measure[data.measure.length - 1]).toBe("total");
    expect(data.y[data.y.length - 1]).toBe(-0.08);
  });

  it("omits the periphery waterfall bar when idiosyncratic contribution is zero", () => {
    const result = fixtureResult();
    result.portfolio_pnl.by_ticker_periphery = { AAPL: 0, MSFT: 0 };
    const data = buildWaterfallData(result, "naive");

    expect(data.x).not.toContain("Periphery");
    expect(data.x[data.x.length - 1]).toBe("Total");
  });

  it("omits visually zero non-material periphery from the waterfall", () => {
    const result = fixtureResult();
    result.portfolio_pnl.by_ticker_periphery = { AAPL: 0.000004, MSFT: 0 };
    const data = buildWaterfallData(result, "naive");

    expect(data.x).not.toContain("Periphery");
    expect(data.x[data.x.length - 1]).toBe("Total");
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

    expect(data.x).toContain("Market");
    expect(data.x).toContain("Sector");
    expect(data.x).toContain("Macro");
    expect(data.x).not.toContain("US large-cap (SPY)");
    expect(data.y[data.x.indexOf("Market")]).toBeCloseTo(-0.04);
    expect(data.y[data.x.indexOf("Sector")]).toBeCloseTo(-0.02);
    expect(data.y[data.x.indexOf("Macro")]).toBeCloseTo(0.01);
  });

  it("explodes material periphery into signed ticker bars", () => {
    const data = buildWaterfallData(fixtureResult(), "naive");

    expect(data.x).toContain("AAPL periphery");
    expect(data.x).not.toContain("Periphery");
    expect(data.y[data.x.indexOf("AAPL periphery")]).toBeCloseTo(-0.02);
  });

  it("does not hide offsetting material periphery behind a zero net bar", () => {
    const result = fixtureResult();
    result.portfolio_pnl.total_pnl = -0.06;
    result.portfolio_pnl.by_ticker_periphery = { AAPL: 0.01, MSFT: -0.01 };

    const data = buildWaterfallData(result, "naive");

    expect(data.x).toContain("AAPL periphery");
    expect(data.x).toContain("MSFT periphery");
    expect(data.x).not.toContain("Periphery");
    expect(data.y[data.x.indexOf("AAPL periphery")]).toBeCloseTo(0.01);
    expect(data.y[data.x.indexOf("MSFT periphery")]).toBeCloseTo(-0.01);
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

    expect(data.x).toContain("AAPL periphery");
    expect(data.x).toContain("MSFT periphery");
    expect(data.x).toContain("NVDA periphery");
    expect(data.x).toContain("Other periphery");
    expect(data.x).not.toContain("AMZN periphery");
    expect(data.x).not.toContain("GOOGL periphery");
    expect(data.y[data.x.indexOf("Other periphery")]).toBeCloseTo(0.001);
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
    expect(usd.x).toEqual(pct.x);
    expect(usd.y[usd.y.length - 1]).toBeCloseTo(-0.08 * nav); // total bar = total_pnl × NAV
    expect(usd.text[usd.text.length - 1]).toContain("$");
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

describe("chartTheme", () => {
  afterEach(() => {
    resetChartThemeForTests();
    document.documentElement.style.removeProperty("--up");
  });

  it("falls back to the Hokusai literals when tokens are unset (jsdom)", () => {
    resetChartThemeForTests();
    const theme = chartTheme();
    expect(theme.up).toBe("#4cc38a");
    expect(theme.down).toBe("#e8615a");
    expect(theme.grid).toBe("rgba(238, 242, 236, 0.08)");
  });

  it("reads root custom properties and memoizes the first read", () => {
    resetChartThemeForTests();
    document.documentElement.style.setProperty("--up", "#123456");
    const first = chartTheme();
    expect(first.up).toBe("#123456");

    // Changing the property after the first read must NOT change the theme —
    // there is no runtime theme switching, so the read is one-shot.
    document.documentElement.style.setProperty("--up", "#654321");
    const second = chartTheme();
    expect(second).toBe(first);
    expect(second.up).toBe("#123456");
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
