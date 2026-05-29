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

export function formatCurrency(value: number, currency = "USD", digits = 0): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: digits,
      minimumFractionDigits: digits
    }).format(value);
  } catch {
    // Unknown/invalid currency code → plain prefixed number.
    return `${currency} ${value.toLocaleString("en-US", { maximumFractionDigits: digits })}`;
  }
}

/** Signed dollar P&L: "+$12,340" / "-$5,400". */
export function formatSignedCurrency(value: number, currency = "USD", digits = 0): string {
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${formatCurrency(value, currency, digits)}`;
}

/**
 * Parse a free-text portfolio value into a positive number, or null.
 * Accepts "$1,000,000", "1,000,000", "1m", "250k", "2.5b". Rejects junk,
 * non-finite, and non-positive (so JSON never carries a silent NaN/null NAV).
 */
export function parseNav(input: string): number | null {
  if (!input) return null;
  const cleaned = input.trim().toLowerCase().replace(/[$,\s]/g, "");
  const match = cleaned.match(/^([0-9]*\.?[0-9]+)([kmb])?$/);
  if (!match) return null;
  const mult = match[2] === "k" ? 1e3 : match[2] === "m" ? 1e6 : match[2] === "b" ? 1e9 : 1;
  const value = parseFloat(match[1]) * mult;
  return Number.isFinite(value) && value > 0 ? value : null;
}

/**
 * Canonical ticker form, mirroring the server's normalize_ticker: trim, then
 * uppercase. A Yahoo suffix after the LAST dot is uppercased too (e.g. "7203.t"
 * -> "7203.T", "brk-b" -> "BRK-B"). Applied live on input so the editor shows
 * exactly what the server will store — no submit-time surprise.
 */
export function normalizeTicker(raw: string): string {
  const s = raw.trim();
  const i = s.lastIndexOf(".");
  return i === -1
    ? s.toUpperCase()
    : `${s.slice(0, i).toUpperCase()}.${s.slice(i + 1).toUpperCase()}`;
}

export interface PositionValuation {
  ticker: string;
  weight: number;
  shares?: number;
  mark?: number;
  markDate?: string;
  value: number; // original USD market value
  stressed: number; // post-shock USD market value
  delta: number; // stressed - value (= NAV * by_ticker_total[t])
  deltaPct: number; // delta / value (= the name's scenario return)
}

/**
 * Original → stressed per-position valuation, all derived from NAV (the engine is
 * linear): value = position_values[t] (marked) ?? weight·NAV (notional);
 * delta = NAV·by_ticker_total[t]; stressed = value + delta.
 */
export function buildPositionValuations(result: ScenarioResult, nav: number): PositionValuation[] {
  return Object.keys(result.portfolio_holdings).map((ticker) => {
    const weight = result.portfolio_holdings[ticker] ?? 0;
    const value = result.position_values?.[ticker] ?? weight * nav;
    const delta = nav * (result.portfolio_pnl.by_ticker_total[ticker] ?? 0);
    return {
      ticker,
      weight,
      shares: result.position_quantities?.[ticker],
      mark: result.mark_prices?.[ticker],
      markDate: result.price_date_by_ticker?.[ticker],
      value,
      stressed: value + delta,
      delta,
      deltaPct: value !== 0 ? delta / value : 0
    };
  });
}

/** A dollar waterfall = the return-space waterfall scaled by NAV. */
export function buildWaterfallDataDollars(
  result: ScenarioResult,
  method: AttributionMethod,
  nav: number,
  currency = "USD"
): WaterfallData {
  const base = buildWaterfallData(result, method);
  return {
    x: base.x,
    y: base.y.map((value) => value * nav),
    measure: base.measure,
    text: base.y.map((value) => formatSignedCurrency(value * nav, currency))
  };
}

