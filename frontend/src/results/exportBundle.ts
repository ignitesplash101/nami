import { buildPositionValuations } from "../charts";
import type { CsvBundleFile, CsvCell } from "../csv";
import { factorDisplayName } from "../factors";
import { slugify } from "../format";
import type {
  FactorMetadataMap,
  ScenarioResult,
  ScenarioRunResponse
} from "../types";

interface BuildResultsCsvBundleInput {
  envelope: ScenarioRunResponse;
  factorMeta: FactorMetadataMap;
  nav: number | null;
}

function scalar(value: unknown): CsvCell {
  if (value == null || typeof value === "string" || typeof value === "number") return value;
  return JSON.stringify(value);
}

function attributionValue(
  values: Record<string, number> | null,
  factor: string
): number | null {
  return values?.[factor] ?? null;
}

function baseFiles({
  envelope,
  factorMeta,
  nav
}: BuildResultsCsvBundleInput): CsvBundleFile[] {
  const result = envelope.result;
  const pnl = result.portfolio_pnl;
  const benchmarkTotal = result.benchmark_pnl?.total_pnl ?? null;
  const summary: CsvBundleFile = {
    filename: "summary.csv",
    headers: ["field", "value"],
    rows: [
      ["scenario", result.scenario_text],
      ["portfolio_key", result.portfolio_key],
      ["portfolio_name", result.portfolio_name],
      ["market_date", result.market_date],
      ["requested_as_of_date", result.requested_as_of_date],
      ["narrative_mode", result.narrative_mode],
      ["portfolio_pnl", pnl.total_pnl],
      ["portfolio_nav", nav],
      ["stressed_nav", nav == null ? null : nav * (1 + pnl.total_pnl)],
      ["reporting_currency", result.reporting_currency ?? "USD"],
      ["benchmark_ticker", result.benchmark_ticker ?? null],
      ["benchmark_pnl", benchmarkTotal],
      ["active_return", result.active_return ?? null],
      ["citations", result.citations.length],
      ["selected_analogs", result.analogs_selected.length],
      ["idio_band_1sigma", result.pnl_uncertainty?.band_1sigma ?? null],
      ["severity_worst", result.severity_ladder?.worst_pnl ?? null],
      ["severity_base", result.severity_ladder?.base_pnl ?? null],
      ["severity_best", result.severity_ladder?.best_pnl ?? null],
      ["analog_replay_min", result.analog_replay?.min_pnl ?? null],
      ["analog_replay_median", result.analog_replay?.median_pnl ?? null],
      ["analog_replay_max", result.analog_replay?.max_pnl ?? null]
    ]
  };

  const shocks = new Map(result.factor_shocks.map((shock) => [shock.factor, shock]));
  const factorKeys = new Set([
    ...result.factor_shocks.map((shock) => shock.factor),
    ...Object.keys(pnl.by_factor_naive),
    ...Object.keys(pnl.by_factor_conditional_shapley ?? {}),
    ...Object.keys(pnl.by_factor_conditional_shapley_explicit ?? {}),
    ...Object.keys(pnl.by_factor_conditional_shapley_grouped ?? {}),
    ...Object.keys(result.factor_envelope)
  ]);
  const drivers: CsvBundleFile = {
    filename: "drivers-and-attribution.csv",
    headers: [
      "factor",
      "factor_label",
      "shock_applied",
      "reasoning",
      "naive_contribution",
      "full_conditional_contribution",
      "explicit_conditional_contribution",
      "grouped_conditional_contribution",
      "envelope_mean",
      "envelope_p10",
      "envelope_p90",
      "envelope_count"
    ],
    rows: [...factorKeys].map((factor) => {
      const envelopeRow = result.factor_envelope[factor];
      const shock = shocks.get(factor);
      return [
        factor,
        factorDisplayName(factorMeta, factor),
        shock?.shock ?? 0,
        shock?.reasoning ?? "",
        pnl.by_factor_naive[factor] ?? 0,
        attributionValue(pnl.by_factor_conditional_shapley, factor),
        attributionValue(pnl.by_factor_conditional_shapley_explicit, factor),
        attributionValue(pnl.by_factor_conditional_shapley_grouped, factor),
        envelopeRow?.mean ?? null,
        envelopeRow?.p10 ?? null,
        envelopeRow?.p90 ?? null,
        envelopeRow?.count ?? null
      ];
    })
  };

  const valuations = nav == null ? [] : buildPositionValuations(result, nav);
  const valuationsByTicker = new Map(valuations.map((row) => [row.ticker, row]));
  const periphery = new Map(result.periphery_shocks.map((shock) => [shock.ticker, shock]));
  const positions: CsvBundleFile = {
    filename: "positions-and-valuation.csv",
    headers: [
      "ticker",
      "weight",
      "factor_contribution",
      "periphery_contribution",
      "total_contribution",
      "periphery_shock",
      "periphery_reasoning",
      "shares",
      "mark",
      "mark_date",
      "value",
      "stressed_value",
      "delta_value",
      "position_return"
    ],
    rows: Object.keys(result.portfolio_holdings).map((ticker) => {
      const valuation = valuationsByTicker.get(ticker);
      const idio = periphery.get(ticker);
      return [
        ticker,
        result.portfolio_holdings[ticker] ?? 0,
        pnl.by_ticker_factor[ticker] ?? 0,
        pnl.by_ticker_periphery[ticker] ?? 0,
        pnl.by_ticker_total[ticker] ?? 0,
        idio?.shock ?? 0,
        idio?.reasoning ?? "",
        valuation?.shares ?? null,
        valuation?.mark ?? null,
        valuation?.markDate ?? null,
        valuation?.value ?? null,
        valuation?.stressed ?? null,
        valuation?.delta ?? null,
        valuation?.deltaPct ?? null
      ];
    })
  };

  const narrative: CsvBundleFile = {
    filename: "narrative.csv",
    headers: ["scenario", "narrative", "mode", "market_date"],
    rows: [[result.scenario_text, result.narrative, result.narrative_mode, result.market_date]]
  };

  const citations: CsvBundleFile = {
    filename: "citations.csv",
    headers: ["title", "url", "snippet"],
    rows: result.citations.map((citation) => [
      citation.title ?? "",
      citation.url,
      citation.snippet ?? null
    ])
  };

  const eventReturns = new Map(
    (result.analog_event_returns ?? []).map((entry) => [entry.event_id, entry])
  );
  const replay = new Map(
    (result.analog_replay?.per_event ?? []).map((entry) => [entry.event_id, entry])
  );
  const analogs: CsvBundleFile = {
    filename: "analogs.csv",
    headers: [
      "event_id",
      "event",
      "start",
      "end",
      "tags",
      "description",
      "why_relevant",
      "window_calendar_days",
      "factor_returns",
      "replay_pnl",
      "factors_covered",
      "factors_total"
    ],
    rows: result.analogs_selected.map((selection) => {
      const event = envelope.analog_events[selection.event_id];
      const returns = eventReturns.get(selection.event_id);
      const replayRow = replay.get(selection.event_id);
      return [
        selection.event_id,
        event?.name ?? selection.event_id,
        event?.start_date ?? null,
        event?.end_date ?? null,
        event?.tags.join("|") ?? "",
        event?.description ?? "",
        selection.why_relevant,
        returns?.window_calendar_days ?? null,
        returns ? JSON.stringify(returns.factor_returns) : null,
        replayRow?.replay_pnl ?? null,
        replayRow?.n_factors_covered ?? null,
        replayRow?.n_factors_total ?? null
      ];
    })
  };

  const diagnostics: CsvBundleFile = {
    filename: "diagnostics.csv",
    headers: ["kind", "severity", "message", "factors", "evidence"],
    rows: (result.risk_diagnostics ?? []).map((diagnostic) => [
      diagnostic.kind,
      diagnostic.severity,
      diagnostic.message,
      diagnostic.factors.join("|"),
      JSON.stringify(diagnostic.evidence)
    ])
  };

  const quality = result.regression_quality;
  const regression: CsvBundleFile = {
    filename: "regression-quality.csv",
    headers: [
      "estimator",
      "lookback_weeks",
      "alpha",
      "min_obs",
      "ticker",
      "r2",
      "r2_adjusted",
      "effective_parameters",
      "observations",
      "idio_vol_weekly"
    ],
    rows: quality
      ? Object.entries(quality.by_ticker).map(([ticker, row]) => [
          quality.estimator,
          quality.lookback_weeks,
          quality.alpha,
          quality.min_obs,
          ticker,
          row.r2,
          row.r2_adj ?? null,
          row.p_eff ?? null,
          row.n_obs,
          row.idio_vol_weekly
        ])
      : []
  };

  const reproducibilitySource = envelope.reproducibility ?? {
    portfolio_key: result.portfolio_key,
    portfolio_holdings: result.portfolio_holdings,
    effective_as_of_date: result.market_date,
    requested_as_of_date: result.requested_as_of_date,
    narrative_mode: result.narrative_mode,
    selected_event_ids: result.selected_event_ids
  };
  const reproducibility: CsvBundleFile = {
    filename: "reproducibility.csv",
    headers: ["field", "value"],
    rows: Object.entries(reproducibilitySource).map(([key, value]) => [key, scalar(value)])
  };

  return [
    summary,
    drivers,
    positions,
    narrative,
    citations,
    analogs,
    diagnostics,
    regression,
    reproducibility
  ];
}

export function buildResultsCsvBundle(input: BuildResultsCsvBundleInput): CsvBundleFile[] {
  const files = baseFiles(input);
  const result = input.envelope.result;
  if (result.adjustment_history.length > 0) {
    files.push({
      filename: "adjustment-history.csv",
      headers: ["adjustment", "kind", "timestamp", "prompt", "factor", "before", "after"],
      rows: result.adjustment_history.flatMap((adjustment, index) =>
        Object.entries(adjustment.changed_factors).map(([factor, [before, after]]) => [
          index + 1,
          adjustment.kind,
          adjustment.timestamp,
          adjustment.prompt_text,
          factor,
          before,
          after
        ])
      )
    });
  }
  if (result.narrative_shapley) {
    files.push({
      filename: "theme-sensitivity.csv",
      headers: [
        "narrative_index",
        "sub_narrative",
        "shapley_pnl",
        "relative_contribution",
        "total_pnl",
        "subsets_evaluated"
      ],
      rows: result.narrative_shapley.contributions.map((contribution) => [
        contribution.narrative_index,
        contribution.narrative_text,
        contribution.shapley_value,
        contribution.relative_contribution,
        result.narrative_shapley?.total_pnl ?? null,
        result.narrative_shapley?.n_subsets_evaluated ?? null
      ])
    });
  }
  return files;
}

export function resultsZipFilename(result: ScenarioResult): string {
  const portfolio = result.portfolio_key === "custom" ? result.portfolio_name : result.portfolio_key;
  return `nami_${slugify(portfolio)}_${slugify(result.scenario_text)}_${result.market_date}_all-results.zip`;
}
