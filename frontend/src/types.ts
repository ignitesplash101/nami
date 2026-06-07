export type AccessMode = "visitor" | "admin";

export interface Permissions {
  custom_portfolio: boolean;
  free_text_scenario: boolean;
  narrative_decomposition: boolean;
}

export interface AccessResponse {
  access_mode: AccessMode;
  admin_available: boolean;
  permissions: Permissions;
  // Latest NYSE regular-close date (YYYY-MM-DD); seeds the as-of picker default.
  latest_market_date: string;
}

export interface SamplePortfolio {
  key: string;
  name: string;
  description: string;
  holdings: Record<string, number>;
  benchmark?: string | null;
}

// ticker -> {sector, country} classification tags for exposure breakdowns.
export type TickerMetadata = Record<string, { sector: string; country: string }>;

export interface FactorMetadata {
  key: string;
  ticker: string;
  group: "market" | "sector" | "style" | "macro" | string;
  short_label: string;
  display_name: string;
  description: string;
}

export type FactorMetadataMap = Record<string, FactorMetadata>;

export interface SampleScenario {
  key: string;
  name: string;
  text: string;
}

export interface AnalogSelection {
  event_id: string;
  why_relevant: string;
}

export interface FactorShock {
  factor: string;
  shock: number;
  reasoning: string;
}

export interface PeripheryShock {
  ticker: string;
  shock: number;
  reasoning: string;
}

export interface Citation {
  url: string;
  title: string | null;
  snippet: string | null;
}

export interface PortfolioPnL {
  total_pnl: number;
  by_factor_naive: Record<string, number>;
  by_factor_conditional_shapley: Record<string, number> | null;
  by_factor_conditional_shapley_explicit: Record<string, number> | null;
  by_factor_conditional_shapley_grouped: Record<string, number> | null;
  by_ticker_factor: Record<string, number>;
  by_ticker_periphery: Record<string, number>;
  by_ticker_total: Record<string, number>;
}

export interface NarrativeContribution {
  narrative_index: number;
  narrative_text: string;
  shapley_value: number;
  relative_contribution: number;
}

export interface NarrativeShapleyResult {
  sub_narratives: string[];
  contributions: NarrativeContribution[];
  subset_pnls: Record<string, number>;
  total_pnl: number;
  n_subsets_evaluated: number;
}

export interface ShockAdjustment {
  kind: "manual" | "prompt";
  prompt_text: string | null;
  timestamp: string;
  changed_factors: Record<string, [number, number]>;
}

export type NarrativeMode = "grounded" | "analog_only";

export interface RiskDiagnostic {
  kind: "correlation_conflict" | "envelope_direction_conflict" | "conditional_cross_credit";
  severity: "info" | "warning";
  message: string;
  factors: string[];
  evidence: Record<string, number | string>;
}

export interface ScenarioResult {
  scenario_text: string;
  market_date: string;  // effective NYSE trading-day as-of date (YYYY-MM-DD)
  portfolio_key: string;
  portfolio_name: string;
  portfolio_holdings: Record<string, number>;
  analogs_selected: AnalogSelection[];
  factor_shocks: FactorShock[];
  periphery_shocks: PeripheryShock[];
  narrative: string;
  citations: Citation[];
  factor_envelope: Record<string, Record<string, number>>;
  portfolio_pnl: PortfolioPnL;
  narrative_shapley: NarrativeShapleyResult | null;
  adjustment_history: ShockAdjustment[];
  risk_diagnostics?: RiskDiagnostic[];
  // Backdating metadata (added Phase 11). Defaults match live runs so older
  // cached payloads deserialize cleanly.
  requested_as_of_date: string | null;
  narrative_mode: NarrativeMode;
  selected_event_ids: string[];
  // Mark-to-market metadata (null on return-only runs). Dollars are DERIVED in
  // the UI as `return_field × portfolio_nav` (the engine is linear), so no dollar
  // P&L is sent — only NAV + the marks/FX used.
  portfolio_nav?: number | null;
  reporting_currency?: string | null;
  position_quantities?: Record<string, number> | null;
  position_values?: Record<string, number> | null; // USD market value per ticker
  mark_prices?: Record<string, number> | null; // raw close, native quote unit
  price_date_by_ticker?: Record<string, string> | null;
  fx_rates?: Record<string, number> | null; // major currency -> USD per unit
  fx_date_by_currency?: Record<string, string> | null;
  // Benchmark / active-return overlay (never cached; null when no benchmark).
  // active_return = portfolio_pnl.total_pnl − benchmark_pnl.total_pnl.
  benchmark_ticker?: string | null;
  benchmark_pnl?: PortfolioPnL | null;
  active_return?: number | null;
}

export interface ScenarioReproducibility {
  model_id: string;
  prompt_version: string;
  factor_universe_version: string;
  events_version: string;
  requested_as_of_date: string;
  effective_as_of_date: string;
  narrative_mode: NarrativeMode;
  beta_lookback_weeks: number;
  ridge_alpha: number;
  selected_event_ids: string[];
  portfolio_holdings: Record<string, number>;
  portfolio_key: string;
  market_data_source: "yfinance";
  nami_engine_version: string;
  portfolio_nav?: number | null;
  reporting_currency?: string | null;
  position_quantities?: Record<string, number> | null;
  position_values?: Record<string, number> | null;
  mark_prices?: Record<string, number> | null;
  price_date_by_ticker?: Record<string, string> | null;
  fx_rates?: Record<string, number> | null;
  fx_date_by_currency?: Record<string, string> | null;
}

export interface AnalogEvent {
  event_id: string;
  name: string;
  start_date: string;
  end_date: string;
  tags: string[];
  description: string;
}

export interface ScenarioRunResponse {
  result: ScenarioResult;
  analog_events: Record<string, AnalogEvent>;
  cache_key: string | null;
  reproducibility: ScenarioReproducibility | null;
}

export interface SavedScenarioListItem {
  id: string;
  name: string;
  tags: string[];
  created_at: string;
  owner_label: string | null;
  portfolio_name: string;
  portfolio_key: string;
  requested_as_of_date: string;
  effective_as_of_date: string;
  narrative_mode: NarrativeMode;
  total_pnl: number;
  portfolio_nav?: number | null;
}

export interface SavedScenarioRecord {
  id: string;
  name: string;
  tags: string[];
  notes: string;
  created_at: string;
  created_by: string;
  owner_label: string | null;
  scenario_text: string;
  portfolio_snapshot_ref: string | null;
  portfolio_holdings: Record<string, number>;
  portfolio_key: string;
  portfolio_name: string;
  analog_events_snapshot: Record<string, AnalogEvent>;
  result: ScenarioResult;
  reproducibility: ScenarioReproducibility;
}

export interface SavedPortfolioRecord {
  id: string;
  name: string;
  description: string;
  created_at: string;
  created_by: string;
  owner_label: string | null;
}

export interface PortfolioSnapshotRecord {
  id: string;
  portfolio_id: string;
  as_of_date: string;
  holdings: Record<string, number>;
  notes: string;
  created_at: string;
  created_by: string;
  owner_label: string | null;
}

export interface ScenarioAdjustRequest {
  cache_key: string;
  overrides?: Record<string, number>;
  adjustment_text?: string;
  // Resent benchmark so the adjusted result keeps its active-return overlay
  // (benchmarks are overlay-only and not recoverable from the cached canonical).
  benchmark?: string | null;
}

export type SsePipelineStage =
  | "cache_check"
  | "cache_hit"
  | "market"
  | "analogs"
  | "envelope"
  | "narrative"
  | "betas"
  | "attribution"
  | "done"
  | "error";

export interface SseProgressEvent {
  stage: SsePipelineStage;
  status?: "start" | "done";
  result?: ScenarioRunResponse;
  message?: string;
}

export interface PortfolioValidationResponse {
  ok: boolean;
  errors: string[];
  normalized_holdings: Record<string, number>;
  total_weight: number;
}

export type AttributionMethod =
  | "naive"
  | "conditional"
  | "conditional_explicit"
  | "conditional_grouped";
