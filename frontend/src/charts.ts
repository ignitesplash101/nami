import type { AttributionMethod, ScenarioResult } from "./types";

export interface WaterfallData {
  x: string[];
  y: number[];
  measure: ("relative" | "total")[];
  text: string[];
}

export interface FactorReasoningRow {
  factor: string;
  shockApplied: number;
  contribution: number;
  reasoning: string;
}

const NO_EXPLICIT_SHOCK = "No explicit LLM shock; attributed via correlation";

export function selectedFactorAttribution(
  result: ScenarioResult,
  method: AttributionMethod
): Record<string, number> {
  const pnl = result.portfolio_pnl;
  if (method === "conditional" && pnl.by_factor_conditional_shapley) {
    return pnl.by_factor_conditional_shapley;
  }
  if (method === "conditional_explicit" && pnl.by_factor_conditional_shapley_explicit) {
    return pnl.by_factor_conditional_shapley_explicit;
  }
  if (method === "conditional_grouped" && pnl.by_factor_conditional_shapley_grouped) {
    return pnl.by_factor_conditional_shapley_grouped;
  }
  return pnl.by_factor_naive;
}

export function hasCorrelationCrossCredit(method: AttributionMethod): boolean {
  // The "full" conditional Shapley is the only mode that attributes to factors the
  // LLM did not explicitly shock (via historical correlation). The explicit-only
  // and grouped modes suppress that behavior — so the "attributed via correlation"
  // caption should only render under method === "conditional".
  return method === "conditional";
}

export function buildWaterfallData(
  result: ScenarioResult,
  method: AttributionMethod
): WaterfallData {
  const byFactor = selectedFactorAttribution(result, method);
  const peripheryTotal = Object.values(result.portfolio_pnl.by_ticker_periphery).reduce(
    (acc, value) => acc + value,
    0
  );
  const bars = Object.entries(byFactor)
    .filter(([, value]) => Math.abs(value) > 1e-6)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 14);
  bars.push(["Periphery", peripheryTotal]);

  const x = [...bars.map(([name]) => name), "Total"];
  const y = [...bars.map(([, value]) => value), result.portfolio_pnl.total_pnl];
  return {
    x,
    y,
    measure: [...bars.map(() => "relative" as const), "total"],
    text: y.map((value) => formatPercent(value))
  };
}

export function factorReasoningRows(
  result: ScenarioResult,
  method: AttributionMethod
): FactorReasoningRow[] {
  const byFactor = selectedFactorAttribution(result, method);
  const shocksByFactor = new Map(result.factor_shocks.map((shock) => [shock.factor, shock]));
  const showCorrelationLabel = hasCorrelationCrossCredit(method);
  return Object.entries(byFactor)
    .map(([factor, contribution]) => {
      const explicitShock = shocksByFactor.get(factor);
      return {
        factor,
        shockApplied: explicitShock?.shock ?? 0,
        contribution,
        reasoning:
          explicitShock?.reasoning ?? (showCorrelationLabel ? NO_EXPLICIT_SHOCK : "")
      };
    })
    .filter((row) => Math.abs(row.contribution) > 1e-6 || row.reasoning !== "")
    .sort((a, b) => a.contribution - b.contribution);
}

export function topContributor(result: ScenarioResult, method: AttributionMethod) {
  const entries = Object.entries(selectedFactorAttribution(result, method));
  if (entries.length === 0) {
    return { factor: "None", contribution: 0, shockApplied: 0 };
  }
  const [factor, contribution] = entries.sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0];
  const explicitShock = result.factor_shocks.find((shock) => shock.factor === factor);
  return { factor, contribution, shockApplied: explicitShock?.shock ?? 0 };
}

export function formatPercent(value: number, digits = 2): string {
  return `${(value * 100).toFixed(digits)}%`;
}

