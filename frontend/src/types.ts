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
}

export interface SamplePortfolio {
  key: string;
  name: string;
  description: string;
  holdings: Record<string, number>;
}

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

export interface ScenarioResult {
  scenario_text: string;
  market_date: string;
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
}

export interface ScenarioAdjustRequest {
  cache_key: string;
  overrides?: Record<string, number>;
  adjustment_text?: string;
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

