import { afterEach, describe, expect, it, vi } from "vitest";
import { strFromU8, unzipSync } from "fflate";
import { downloadCsvZip, toCsv } from "../csv";
import type { ScenarioResult, ScenarioRunResponse } from "../types";
import { buildResultsCsvBundle, resultsZipFilename } from "./exportBundle";

function resultFixture(): ScenarioResult {
  return {
    scenario_text: "Supply shock 日本",
    market_date: "2026-07-15",
    portfolio_key: "sample_book",
    portfolio_name: "Sample book",
    portfolio_holdings: { AAPL: 1 },
    analogs_selected: [{ event_id: "event-1", why_relevant: "same mechanism" }],
    factor_shocks: [{ factor: "SPY", shock: -0.1, reasoning: "-led selloff" }],
    periphery_shocks: [{ ticker: "AAPL", shock: -0.02, reasoning: "earnings exposure" }],
    narrative: "A cited narrative.",
    citations: [
      { title: "=Formula source 日本", url: "https://example.com/source", snippet: "Evidence" }
    ],
    factor_envelope: { SPY: { mean: -0.08, p10: -0.12, p90: -0.04, count: 4 } },
    portfolio_pnl: {
      total_pnl: -0.12,
      by_factor_naive: { SPY: -0.1 },
      by_factor_conditional_shapley: { SPY: -0.1 },
      by_factor_conditional_shapley_explicit: { SPY: -0.1 },
      by_factor_conditional_shapley_grouped: { SPY: -0.1 },
      by_ticker_factor: { AAPL: -0.1 },
      by_ticker_periphery: { AAPL: -0.02 },
      by_ticker_total: { AAPL: -0.12 }
    },
    narrative_shapley: {
      sub_narratives: ["Supply disruption", "Policy response"],
      contributions: [
        {
          narrative_index: 0,
          narrative_text: "Supply disruption",
          shapley_value: -0.08,
          relative_contribution: 0.67
        }
      ],
      subset_pnls: { "1": -0.08 },
      total_pnl: -0.12,
      n_subsets_evaluated: 3
    },
    adjustment_history: [
      {
        kind: "manual",
        prompt_text: null,
        timestamp: "2026-07-15T10:00:00Z",
        changed_factors: { SPY: [-0.08, -0.1] }
      }
    ],
    risk_diagnostics: [
      {
        kind: "band_coverage",
        severity: "warning",
        message: "Limited evidence",
        factors: ["SPY"],
        evidence: { covered: 1 }
      }
    ],
    regression_quality: {
      estimator: "ridge",
      lookback_weeks: 156,
      alpha: 0.1,
      min_obs: 40,
      by_ticker: { AAPL: { r2: 0.8, n_obs: 150, idio_vol_weekly: 0.02 } }
    },
    analog_event_returns: [
      { event_id: "event-1", window_calendar_days: 30, factor_returns: { SPY: -0.1 } }
    ],
    analog_replay: {
      per_event: [
        { event_id: "event-1", replay_pnl: -0.11, n_factors_covered: 25, n_factors_total: 26 }
      ],
      min_pnl: -0.11,
      median_pnl: -0.11,
      max_pnl: -0.11
    },
    pnl_uncertainty: { band_1sigma: 0.02, portfolio_idio_vol_weekly: 0.01, horizon_weeks: 4 },
    severity_ladder: {
      worst_pnl: -0.16,
      base_pnl: -0.12,
      best_pnl: -0.06,
      n_banded: 1,
      n_held: 0
    },
    requested_as_of_date: "2026-07-15",
    narrative_mode: "grounded",
    selected_event_ids: ["event-1"],
    benchmark_ticker: "SPY",
    benchmark_pnl: null,
    active_return: -0.02
  };
}

function envelopeFixture(): ScenarioRunResponse {
  return {
    result: resultFixture(),
    analog_events: {
      "event-1": {
        event_id: "event-1",
        name: "Historical event",
        start_date: "2020-01-01",
        end_date: "2020-01-31",
        tags: ["supply"],
        description: "Historical disruption"
      }
    },
    cache_key: "cache-1",
    reproducibility: {
      model_id: "model",
      prompt_version: "v11",
      factor_universe_version: "factors",
      events_version: "events",
      requested_as_of_date: "2026-07-15",
      effective_as_of_date: "2026-07-15",
      narrative_mode: "grounded",
      beta_lookback_weeks: 156,
      ridge_alpha: 0.1,
      selected_event_ids: ["event-1"],
      portfolio_holdings: { AAPL: 1 },
      portfolio_key: "sample_book",
      market_data_source: "yfinance",
      nami_engine_version: "engine"
    }
  };
}

afterEach(() => vi.unstubAllGlobals());

function blobBytes(blob: Blob): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.readAsArrayBuffer(blob);
  });
}

describe("all-results export bundle", () => {
  it("builds the required files and conditional files from committed result state", () => {
    const files = buildResultsCsvBundle({ envelope: envelopeFixture(), factorMeta: {}, nav: 100_000 });
    expect(files.map((file) => file.filename)).toEqual([
      "summary.csv",
      "drivers-and-attribution.csv",
      "positions-and-valuation.csv",
      "narrative.csv",
      "citations.csv",
      "analogs.csv",
      "diagnostics.csv",
      "regression-quality.csv",
      "reproducibility.csv",
      "adjustment-history.csv",
      "theme-sensitivity.csv"
    ]);
    expect(resultsZipFilename(envelopeFixture().result)).toBe(
      "nami_sample-book_supply-shock_2026-07-15_all-results.zip"
    );
  });

  it("omits conditional files when the committed result has no adjustments or themes", () => {
    const envelope = envelopeFixture();
    envelope.result.adjustment_history = [];
    envelope.result.narrative_shapley = null;
    const names = buildResultsCsvBundle({ envelope, factorMeta: {}, nav: null }).map(
      (file) => file.filename
    );
    expect(names).not.toContain("adjustment-history.csv");
    expect(names).not.toContain("theme-sensitivity.csv");
  });

  it("includes Quant V2 range, support, exposure, and source provenance", () => {
    const envelope = envelopeFixture();
    envelope.result.engine_mode = "quant_v2";
    envelope.result.historical_model_range = {
      label: "historical_model_range",
      p10: -0.2,
      p50: -0.1,
      p90: -0.03,
      draws: 4096,
      seed: 1729
    };
    envelope.result.quant_support = {
      candidate_count: 1000,
      direction_compatible_count: 300,
      neighbor_count: 50,
      effective_sample_size: 41.2,
      medoid_date: "2020-03-16",
      nearest_distance: 0.4,
      kernel_bandwidth: 1.2,
      query_dates: ["2020-03-16"],
      data_start: "2007-07-01",
      data_end: "2026-07-15"
    };
    envelope.result.quant_exposures = {
      AAPL: {
        region: "north_america",
        tier: "estimated",
        n_obs: 156,
        data_weight: 1,
        coefficients: { "NA:MKT_RF": 1.1 }
      }
    };
    envelope.result.quant_source_versions = {
      north_america: {
        dataset_id: "ff-na",
        url: "https://example.com/factors",
        sha256: "abc123",
        retrieved_at: "2026-07-15T00:00:00Z"
      }
    };

    const files = buildResultsCsvBundle({ envelope, factorMeta: {}, nav: null });
    const names = files.map((file) => file.filename);
    expect(names).toContain("historical-model-range.csv");
    expect(names).toContain("quant-support.csv");
    expect(names).toContain("quant-exposures.csv");
    expect(names).toContain("quant-sources.csv");
    expect(files.find((file) => file.filename === "quant-exposures.csv")?.rows).toContainEqual([
      "AAPL",
      "north_america",
      "estimated",
      156,
      1,
      null,
      null,
      "NA:MKT_RF",
      1.1
    ]);
  });

  it("omits Quant CSVs for serialized legacy empty defaults", () => {
    const envelope = envelopeFixture();
    envelope.result.quant_exposures = {};
    envelope.result.quant_source_versions = {};

    const names = buildResultsCsvBundle({ envelope, factorMeta: {}, nav: null }).map(
      (file) => file.filename
    );

    expect(names).not.toContain("quant-exposures.csv");
    expect(names).not.toContain("quant-sources.csv");
  });

  it("writes a real ZIP whose every CSV has a UTF-8 BOM and formula protection", async () => {
    const createObjectURL = vi.fn((_blob: Blob) => "blob:all-results");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const files = buildResultsCsvBundle({ envelope: envelopeFixture(), factorMeta: {}, nav: null });

    await downloadCsvZip("results.zip", files);

    const createdBlob = createObjectURL.mock.calls[0]?.[0] as Blob | undefined;
    expect(createdBlob).toBeDefined();
    if (!createdBlob) throw new Error("ZIP Blob was not created");
    const zipped = await blobBytes(createdBlob);
    const entries = unzipSync(zipped);
    expect(Object.keys(entries)).toEqual(files.map((file) => file.filename));
    for (const bytes of Object.values(entries)) {
      expect(Array.from(bytes.slice(0, 3))).toEqual([0xef, 0xbb, 0xbf]);
    }
    const citations = strFromU8(entries["citations.csv"]);
    expect(citations).toContain("'=Formula source 日本");
    expect(toCsv(files[0].headers, files[0].rows)).not.toMatch(/^\uFEFF/);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:all-results");
    click.mockRestore();
  });
});
