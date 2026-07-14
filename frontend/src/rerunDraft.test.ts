import { describe, expect, it } from "vitest";
import { buildRerunDraft } from "./rerunDraft";
import type { ScenarioResult } from "./types";

/** Minimal live, grounded, sample-book result; each test overlays only the
 * fields it exercises so the trap it targets is obvious. */
function baseResult(overrides: Partial<ScenarioResult> = {}): ScenarioResult {
  return {
    scenario_text: "Risk-off shock",
    market_date: "2026-05-28",
    portfolio_key: "us_tech_growth",
    portfolio_name: "US tech growth",
    portfolio_holdings: { AAPL: 0.6, MSFT: 0.4 },
    analogs_selected: [],
    factor_shocks: [{ factor: "SPY", shock: -0.1, reasoning: "broad selloff" }],
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
      by_ticker_factor: { AAPL: -0.05, MSFT: -0.03 },
      by_ticker_periphery: { AAPL: 0, MSFT: 0 },
      by_ticker_total: { AAPL: -0.05, MSFT: -0.03 }
    },
    narrative_shapley: null,
    adjustment_history: [],
    requested_as_of_date: "2026-05-28",
    narrative_mode: "grounded",
    selected_event_ids: [],
    ...overrides
  };
}

const SAMPLE_KEYS = ["us_tech_growth", "msci_world", "defensive_mix", "japan_equity"];

describe("buildRerunDraft", () => {
  it("restores a recognized sample key as a sample-mode draft", () => {
    const draft = buildRerunDraft(baseResult(), { sampleKeys: SAMPLE_KEYS, isAdmin: false });
    expect(draft.portfolio).toEqual({ mode: "sample", key: "us_tech_growth" });
    expect(draft.scenarioText).toBe("Risk-off shock");
  });

  it("carries the scenario text verbatim", () => {
    const draft = buildRerunDraft(baseResult({ scenario_text: "Custom authored stress" }), {
      sampleKeys: SAMPLE_KEYS,
      isAdmin: true
    });
    expect(draft.scenarioText).toBe("Custom authored stress");
  });

  it("rebuilds a custom book from holdings when the key is not a sample key", () => {
    const draft = buildRerunDraft(
      baseResult({
        portfolio_key: "custom",
        portfolio_name: "My book",
        portfolio_holdings: { NVDA: 0.7, TSLA: 0.3 }
      }),
      { sampleKeys: SAMPLE_KEYS, isAdmin: true }
    );
    expect(draft.portfolio).toEqual({
      mode: "custom",
      name: "My book",
      rows: [
        { ticker: "NVDA", weight: 0.7 },
        { ticker: "TSLA", weight: 0.3 }
      ],
      units: "weights"
    });
  });

  it("falls back to a default name when a custom book has no name", () => {
    const draft = buildRerunDraft(
      baseResult({ portfolio_key: "custom", portfolio_name: "", portfolio_holdings: { NVDA: 1 } }),
      { sampleKeys: SAMPLE_KEYS, isAdmin: true }
    );
    expect(draft.portfolio).toMatchObject({ mode: "custom", name: "Custom Book" });
  });

  it("converts a shares/MTM result to a weights-mode book and flags the conversion", () => {
    // Shares results store server-derived weights in portfolio_holdings; the
    // draft is always weights-mode and never resurrects the share counts.
    const draft = buildRerunDraft(
      baseResult({
        portfolio_key: "custom",
        portfolio_name: "Marked book",
        portfolio_holdings: { AAPL: 0.55, MSFT: 0.45 },
        position_quantities: { AAPL: 100, MSFT: 50 },
        portfolio_nav: 250000
      }),
      { sampleKeys: SAMPLE_KEYS, isAdmin: true }
    );
    expect(draft.sharesConversion).toBe(true);
    expect(draft.portfolio).toEqual({
      mode: "custom",
      name: "Marked book",
      rows: [
        { ticker: "AAPL", weight: 0.55 },
        { ticker: "MSFT", weight: 0.45 }
      ],
      units: "weights"
    });
    expect(draft.nav).toBe(250000);
  });

  it("does not flag sharesConversion for a return-only (weights) result", () => {
    const draft = buildRerunDraft(baseResult(), { sampleKeys: SAMPLE_KEYS, isAdmin: false });
    expect(draft.sharesConversion).toBe(false);
  });

  it("restores the requested date for a backdated (analog_only) result", () => {
    const draft = buildRerunDraft(
      baseResult({
        market_date: "2020-03-20",
        requested_as_of_date: "2020-03-23",
        narrative_mode: "analog_only"
      }),
      { sampleKeys: SAMPLE_KEYS, isAdmin: true }
    );
    expect(draft.asOf).toEqual({ kind: "backdated", date: "2020-03-23" });
  });

  it("clears the as-of picker for a live (grounded) result", () => {
    // A saved live run reopened long after still reads grounded even though its
    // requested date is now in the past — it must NOT restore as backdated.
    const draft = buildRerunDraft(
      baseResult({ requested_as_of_date: "2024-01-05", narrative_mode: "grounded" }),
      { sampleKeys: SAMPLE_KEYS, isAdmin: true }
    );
    expect(draft.asOf).toEqual({ kind: "live" });
  });

  it("treats analog_only with a missing requested date as live (no date to restore)", () => {
    const draft = buildRerunDraft(
      baseResult({ requested_as_of_date: null, narrative_mode: "analog_only" }),
      { sampleKeys: SAMPLE_KEYS, isAdmin: true }
    );
    expect(draft.asOf).toEqual({ kind: "live" });
  });

  it("passes the benchmark ticker through", () => {
    const draft = buildRerunDraft(baseResult({ benchmark_ticker: "QQQ" }), {
      sampleKeys: SAMPLE_KEYS,
      isAdmin: false
    });
    expect(draft.benchmark).toBe("QQQ");
  });

  it("defaults benchmark to null when absent", () => {
    const draft = buildRerunDraft(baseResult(), { sampleKeys: SAMPLE_KEYS, isAdmin: false });
    expect(draft.benchmark).toBeNull();
  });

  it("passes portfolio_nav through and defaults to null when absent", () => {
    expect(
      buildRerunDraft(baseResult({ portfolio_nav: 1000000 }), {
        sampleKeys: SAMPLE_KEYS,
        isAdmin: false
      }).nav
    ).toBe(1000000);
    expect(
      buildRerunDraft(baseResult(), { sampleKeys: SAMPLE_KEYS, isAdmin: false }).nav
    ).toBeNull();
  });

  it("flags needsAdmin for a visitor restoring a custom portfolio", () => {
    const draft = buildRerunDraft(
      baseResult({ portfolio_key: "custom", portfolio_holdings: { NVDA: 1 } }),
      { sampleKeys: SAMPLE_KEYS, isAdmin: false }
    );
    expect(draft.needsAdmin).toBe(true);
    expect(draft.needsAdminReason).toContain("custom portfolio");
  });

  it("flags needsAdmin for a visitor restoring a backdated result", () => {
    const draft = buildRerunDraft(
      baseResult({ requested_as_of_date: "2020-03-23", narrative_mode: "analog_only" }),
      { sampleKeys: SAMPLE_KEYS, isAdmin: false }
    );
    expect(draft.needsAdmin).toBe(true);
    expect(draft.needsAdminReason).toContain("backdated");
  });

  it("names both reasons when a visitor draft is custom AND backdated", () => {
    const draft = buildRerunDraft(
      baseResult({
        portfolio_key: "custom",
        portfolio_holdings: { NVDA: 1 },
        requested_as_of_date: "2020-03-23",
        narrative_mode: "analog_only"
      }),
      { sampleKeys: SAMPLE_KEYS, isAdmin: false }
    );
    expect(draft.needsAdmin).toBe(true);
    expect(draft.needsAdminReason).toContain("custom portfolio");
    expect(draft.needsAdminReason).toContain("backdated");
  });

  it("does not flag needsAdmin for an admin restoring a custom portfolio", () => {
    const draft = buildRerunDraft(
      baseResult({ portfolio_key: "custom", portfolio_holdings: { NVDA: 1 } }),
      { sampleKeys: SAMPLE_KEYS, isAdmin: true }
    );
    expect(draft.needsAdmin).toBe(false);
    expect(draft.needsAdminReason).toBe("");
  });

  it("does not flag needsAdmin for a visitor restoring a live sample book", () => {
    const draft = buildRerunDraft(baseResult(), { sampleKeys: SAMPLE_KEYS, isAdmin: false });
    expect(draft.needsAdmin).toBe(false);
  });
});
