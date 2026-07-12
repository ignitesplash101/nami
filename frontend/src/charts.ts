import { FALLBACK_FACTORS, factorDisplayName } from "./factors";
import type {
  AnalogEvent,
  AttributionMethod,
  FactorMetadataMap,
  ScenarioResult,
  TickerMetadata
} from "./types";

export interface WaterfallData {
  x: string[];
  y: number[];
  measure: ("relative" | "total")[];
  text: string[];
  hoverText: string[];
}

export interface FactorReasoningRow {
  factor: string;
  factorLabel: string;
  shockApplied: number;
  contribution: number;
  reasoning: string;
  isCorrelationCredit: boolean;
}

const NO_EXPLICIT_SHOCK = "Correlation credit; no explicit shock";
const EPSILON = 1e-6;
const PERIPHERY_GROSS_THRESHOLD = 0.0025;
const PERIPHERY_SINGLE_NAME_THRESHOLD = 0.0015;
const PERIPHERY_TOTAL_SHARE_THRESHOLD = 0.2;
const PERIPHERY_MAX_VISIBLE_NAMES = 3;
const PERIPHERY_DISPLAY_THRESHOLD = 0.00005;
const GROUP_ORDER = ["market", "sector", "style", "macro"];
const GROUP_LABELS: Record<string, string> = {
  market: "Market",
  sector: "Sector",
  style: "Style",
  macro: "Macro"
};

interface WaterfallBar {
  label: string;
  value: number;
  hoverLabel: string;
}

// --- Plotly theme from CSS tokens --------------------------------------------

export interface ChartTheme {
  text: string; // --text
  fontMono: string; // --font-mono
  up: string; // --up
  down: string; // --down
  total: string; // --accent-2
  grid: string; // --chart-grid
  connector: string; // --chart-connector
}

// Fallbacks mirror the current Hokusai Deep literals for jsdom/SSR where the
// stylesheet isn't applied.
const CHART_THEME_FALLBACK: ChartTheme = {
  text: "#eef2ec",
  fontMono: '"IBM Plex Mono", ui-monospace, SFMono-Regular, monospace',
  up: "#4cc38a",
  down: "#e8615a",
  total: "#7fb5d6",
  grid: "rgba(238, 242, 236, 0.08)",
  connector: "rgba(233, 216, 166, 0.3)"
};

let cachedChartTheme: ChartTheme | null = null;
let cachedChartThemeKey: string | null = null;

/** Reads the design tokens from :root, memoized PER THEME — the cache key is
 * `<html data-theme>`, so a theme toggle self-invalidates on the next read
 * (useTheme() re-renders the chart consumers, which call this again). Unset
 * properties fall back per-key to the dark literals so charts render
 * identically without a stylesheet. */
export function chartTheme(): ChartTheme {
  if (typeof document === "undefined") return CHART_THEME_FALLBACK;
  const themeKey = document.documentElement.dataset.theme ?? "dark";
  if (cachedChartTheme && cachedChartThemeKey === themeKey) return cachedChartTheme;
  const styles = getComputedStyle(document.documentElement);
  const read = (name: string, fallback: string): string =>
    styles.getPropertyValue(name).trim() || fallback;
  cachedChartTheme = {
    text: read("--text", CHART_THEME_FALLBACK.text),
    fontMono: read("--font-mono", CHART_THEME_FALLBACK.fontMono),
    up: read("--up", CHART_THEME_FALLBACK.up),
    down: read("--down", CHART_THEME_FALLBACK.down),
    total: read("--accent-2", CHART_THEME_FALLBACK.total),
    grid: read("--chart-grid", CHART_THEME_FALLBACK.grid),
    connector: read("--chart-connector", CHART_THEME_FALLBACK.connector)
  };
  cachedChartThemeKey = themeKey;
  return cachedChartTheme;
}

export function resetChartThemeForTests(): void {
  cachedChartTheme = null;
  cachedChartThemeKey = null;
}

export function preferredAttributionMethod(result: ScenarioResult): AttributionMethod {
  if (result.portfolio_pnl.by_factor_conditional_shapley_explicit) {
    return "conditional_explicit";
  }
  if (result.portfolio_pnl.by_factor_conditional_shapley_grouped) {
    return "conditional_grouped";
  }
  return "naive";
}

/** THE production attribution (Phase 31i: one methodology, two zooms).
 * Explicit conditional Shapley when the engine computed it — efficiency
 * (sums to factor P&L), symmetry (correlated shocks share credit), and
 * unshocked factors stay exactly 0. Falls back to the engine's naive algebra
 * (degraded=true) for old/degraded payloads where the SHAP fit is absent. */
export function selectMainAttribution(result: ScenarioResult): {
  method: AttributionMethod;
  degraded: boolean;
} {
  if (result.portfolio_pnl.by_factor_conditional_shapley_explicit) {
    return { method: "conditional_explicit", degraded: false };
  }
  return { method: "naive", degraded: true };
}

/** Zoom level for the main waterfall: "group" rolls the SAME factor map into
 * market/sector/style/macro bars, so the two zooms reconcile by construction. */
export type AttributionZoom = "factor" | "group";

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
  method: AttributionMethod,
  factors?: FactorMetadataMap,
  zoom: AttributionZoom = "factor"
): WaterfallData {
  const bars = [
    ...factorWaterfallBars(result, method, factors, zoom),
    ...peripheryWaterfallBars(result)
  ];

  const x = [...bars.map((bar) => bar.label), "Total"];
  const y = [...bars.map((bar) => bar.value), result.portfolio_pnl.total_pnl];
  return {
    x,
    y,
    measure: [...bars.map(() => "relative" as const), "total"],
    text: y.map((value) => formatPercent(value)),
    hoverText: [
      ...bars.map((bar) => `${bar.hoverLabel}<br>${formatPercent(bar.value)}`),
      `Total<br>${formatPercent(result.portfolio_pnl.total_pnl)}`
    ]
  };
}

function factorWaterfallBars(
  result: ScenarioResult,
  method: AttributionMethod,
  factors?: FactorMetadataMap,
  zoom: AttributionZoom = "factor"
): WaterfallBar[] {
  const byFactor = selectedFactorAttribution(result, method);
  if (method === "conditional_grouped" || zoom === "group") {
    return groupedFactorBars(byFactor, factors);
  }
  return Object.entries(byFactor)
    .filter(([, value]) => Math.abs(value) > EPSILON)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 14)
    .map(([factor, value]) => ({
      label: factorDisplayName(factors, factor, "short"),
      value,
      hoverLabel: factorDisplayName(factors, factor)
    }));
}

function groupedFactorBars(
  byFactor: Record<string, number>,
  factors?: FactorMetadataMap
): WaterfallBar[] {
  const totals = new Map<string, number>();
  for (const [factor, value] of Object.entries(byFactor)) {
    const group = factorGroup(factors, factor);
    totals.set(group, (totals.get(group) ?? 0) + value);
  }

  return [...totals.entries()]
    .filter(([, value]) => Math.abs(value) > EPSILON)
    .sort(([a], [b]) => groupSortIndex(a) - groupSortIndex(b))
    .map(([group, value]) => {
      const label = factorGroupLabel(group);
      return {
        label,
        value,
        hoverLabel: `${label} factor group`
      };
    });
}

function factorGroup(factors: FactorMetadataMap | undefined, factor: string): string {
  return factors?.[factor]?.group ?? FALLBACK_FACTORS[factor]?.group ?? "other";
}

function groupSortIndex(group: string): number {
  const index = GROUP_ORDER.indexOf(group);
  return index === -1 ? GROUP_ORDER.length : index;
}

function factorGroupLabel(group: string): string {
  if (GROUP_LABELS[group]) return GROUP_LABELS[group];
  return group
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function peripheryWaterfallBars(result: ScenarioResult): WaterfallBar[] {
  const entries = Object.entries(result.portfolio_pnl.by_ticker_periphery)
    .filter(([, value]) => Math.abs(value) > EPSILON)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const peripheryTotal = Object.values(result.portfolio_pnl.by_ticker_periphery).reduce(
    (acc, value) => acc + value,
    0
  );
  const gross = entries.reduce((acc, [, value]) => acc + Math.abs(value), 0);

  if (gross <= EPSILON) {
    return [];
  }

  if (!shouldExpandPeriphery(entries, result.portfolio_pnl.total_pnl)) {
    if (Math.abs(peripheryTotal) < PERIPHERY_DISPLAY_THRESHOLD) {
      return [];
    }
    return [
      {
        label: "Periphery",
        value: peripheryTotal,
        hoverLabel: "Periphery idiosyncratic shocks"
      }
    ];
  }

  const visible = entries.slice(0, PERIPHERY_MAX_VISIBLE_NAMES);
  const bars = visible.map(([ticker, value]) => ({
    label: `${ticker} periphery`,
    value,
    hoverLabel: `${ticker} idiosyncratic shock`
  }));
  const visibleTotal = visible.reduce((acc, [, value]) => acc + value, 0);
  const other = peripheryTotal - visibleTotal;
  if (Math.abs(other) > EPSILON) {
    bars.push({
      label: "Other periphery",
      value: other,
      hoverLabel: "Other idiosyncratic shocks"
    });
  }
  return bars;
}

function shouldExpandPeriphery(entries: [string, number][], totalPnl: number): boolean {
  const gross = entries.reduce((acc, [, value]) => acc + Math.abs(value), 0);
  if (gross <= EPSILON) return false;

  const maxName = Math.max(...entries.map(([, value]) => Math.abs(value)));
  const totalShareTriggered =
    Math.abs(totalPnl) > EPSILON &&
    gross >= PERIPHERY_TOTAL_SHARE_THRESHOLD * Math.abs(totalPnl);
  return (
    gross >= PERIPHERY_GROSS_THRESHOLD ||
    totalShareTriggered ||
    maxName >= PERIPHERY_SINGLE_NAME_THRESHOLD
  );
}

export function factorReasoningRows(
  result: ScenarioResult,
  method: AttributionMethod,
  factors?: FactorMetadataMap
): FactorReasoningRow[] {
  const byFactor = selectedFactorAttribution(result, method);
  const shocksByFactor = new Map(result.factor_shocks.map((shock) => [shock.factor, shock]));
  const showCorrelationLabel = hasCorrelationCrossCredit(method);
  return Object.entries(byFactor)
    .map(([factor, contribution]) => {
      const explicitShock = shocksByFactor.get(factor);
      return {
        factor,
        factorLabel: factorDisplayName(factors, factor),
        shockApplied: explicitShock?.shock ?? 0,
        contribution,
        isCorrelationCredit: !explicitShock && showCorrelationLabel,
        reasoning:
          explicitShock?.reasoning ?? (showCorrelationLabel ? NO_EXPLICIT_SHOCK : "")
      };
    })
    .filter((row) => Math.abs(row.contribution) > 1e-6 || row.reasoning !== "")
    .sort((a, b) => a.contribution - b.contribution);
}

export function topContributor(
  result: ScenarioResult,
  method: AttributionMethod,
  factors?: FactorMetadataMap
) {
  const entries = Object.entries(selectedFactorAttribution(result, method));
  if (entries.length === 0) {
    return { factor: "None", factorLabel: "None", contribution: 0, shockApplied: 0 };
  }
  const [factor, contribution] = entries.sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0];
  const explicitShock = result.factor_shocks.find((shock) => shock.factor === factor);
  return {
    factor,
    factorLabel: factorDisplayName(factors, factor),
    contribution,
    shockApplied: explicitShock?.shock ?? 0
  };
}

export function formatPercent(value: number, digits = 2): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export interface AnalogReplayRow {
  eventId: string;
  name: string;
  pnl: number;
  covered: number;
  total: number;
}

/**
 * Rows for the analog-replay strip, in selection order. Null when the result
 * carries no replay block (older cached/saved payloads — "not computed", never
 * zero). Event names come from the run's analog-events map when available and
 * fall back to the raw event id.
 */
export function buildAnalogReplayRows(
  result: ScenarioResult,
  analogEvents: Record<string, AnalogEvent> | null
): AnalogReplayRow[] | null {
  const replay = result.analog_replay;
  if (!replay || replay.per_event.length === 0) return null;
  return replay.per_event.map((entry) => ({
    eventId: entry.event_id,
    name: analogEvents?.[entry.event_id]?.name ?? entry.event_id,
    pnl: entry.replay_pnl,
    covered: entry.n_factors_covered,
    total: entry.n_factors_total
  }));
}

export interface ScenarioReadout {
  headline: string;
  totalPnl: number;
  direction: "gain" | "loss" | "flat";
  topFactor: string;
  topContribution: number;
  activeReturn: number | null;
  benchmarkTicker: string | null;
  analogCount: number;
  citationCount: number;
  // ±1σ idio dispersion half-width (decimal); null on older payloads.
  idioBand: number | null;
}

/**
 * Answer-first summary of a scenario result: a plain-language one-liner plus the
 * headline numbers. Educational framing only — describes the modeled outcome,
 * never advises. "flat" is anything within ±5bps.
 */
export function buildReadout(
  result: ScenarioResult,
  method: AttributionMethod,
  factors?: FactorMetadataMap
): ScenarioReadout {
  const total = result.portfolio_pnl.total_pnl;
  const top = topContributor(result, method, factors);
  const direction = total > 0.0005 ? "gain" : total < -0.0005 ? "loss" : "flat";
  const magnitude = formatPercent(Math.abs(total));
  const headline =
    direction === "flat"
      ? `In this scenario the portfolio is roughly flat (${formatPercent(total)}), with ${top.factorLabel} the largest modeled driver.`
      : `In this scenario the portfolio ${direction === "gain" ? "gains" : "loses"} ${magnitude}, driven mostly by ${top.factorLabel}.`;
  return {
    headline,
    totalPnl: total,
    direction,
    topFactor: top.factorLabel,
    topContribution: top.contribution,
    activeReturn: result.active_return ?? null,
    benchmarkTicker: result.benchmark_ticker ?? null,
    analogCount: result.analogs_selected.length,
    citationCount: result.citations.length,
    idioBand: result.pnl_uncertainty?.band_1sigma ?? null
  };
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

export interface TagExposureRow {
  tag: string; // sector or country bucket
  weight: number; // summed portfolio weight in the bucket
  pnl: number; // summed scenario return contribution (by_ticker_total)
}

/**
 * Group holdings into sector/country buckets for an exposure breakdown. Weight
 * is the summed portfolio weight; `pnl` is the summed `by_ticker_total` (the
 * name-level scenario return contribution). Unknown tickers fall into "Unknown".
 * Rows are sorted by descending weight.
 */
export function groupByTag(
  result: ScenarioResult,
  meta: TickerMetadata,
  dimension: "sector" | "country"
): TagExposureRow[] {
  const buckets = new Map<string, { weight: number; pnl: number }>();
  for (const ticker of Object.keys(result.portfolio_holdings)) {
    const tag = meta[ticker]?.[dimension] ?? "Unknown";
    const prior = buckets.get(tag) ?? { weight: 0, pnl: 0 };
    prior.weight += result.portfolio_holdings[ticker] ?? 0;
    prior.pnl += result.portfolio_pnl.by_ticker_total[ticker] ?? 0;
    buckets.set(tag, prior);
  }
  return [...buckets.entries()]
    .map(([tag, v]) => ({ tag, weight: v.weight, pnl: v.pnl }))
    .sort((a, b) => b.weight - a.weight);
}

/** A dollar waterfall = the return-space waterfall scaled by NAV. */
export function buildWaterfallDataDollars(
  result: ScenarioResult,
  method: AttributionMethod,
  nav: number,
  currency = "USD",
  factors?: FactorMetadataMap,
  zoom: AttributionZoom = "factor"
): WaterfallData {
  const base = buildWaterfallData(result, method, factors, zoom);
  return {
    x: base.x,
    y: base.y.map((value) => value * nav),
    measure: base.measure,
    text: base.y.map((value) => formatSignedCurrency(value * nav, currency)),
    hoverText: base.hoverText.map((text, index) => {
      const value = base.y[index] ?? 0;
      return `${text}<br>${formatSignedCurrency(value * nav, currency)}`;
    })
  };
}

/** One row of the free book profile's exposure list. */
export interface BookExposureRow {
  key: string;
  label: string;
  exposure: number;
}

/** Top-|exposure| portfolio betas (Σ weight × beta per factor) for the free
 *  book profile — presentation-sorted, engine values untouched. */
export function buildBookProfileRows(
  exposures: Record<string, number>,
  labelFor: (key: string) => string,
  limit = 10
): BookExposureRow[] {
  return Object.entries(exposures)
    .map(([key, exposure]) => ({ key, label: labelFor(key), exposure }))
    .sort((a, b) => Math.abs(b.exposure) - Math.abs(a.exposure))
    .slice(0, limit);
}

/** True when two envelopes display the same scenario outcome. Keys off
 *  always-present result fields — cache_key/reproducibility are null on the
 *  adjust/decompose/saved paths. The total_pnl term makes an adjusted variant
 *  of the same canonical read as DIFFERENT, so pinned-canonical vs adjusted
 *  comparisons render. */
export function sameScenarioResult(a: ScenarioResult, b: ScenarioResult): boolean {
  return (
    a.scenario_text === b.scenario_text &&
    a.market_date === b.market_date &&
    a.portfolio_key === b.portfolio_key &&
    a.portfolio_pnl.total_pnl === b.portfolio_pnl.total_pnl
  );
}

/** The lowest common attribution method BOTH results can serve — a comparison
 *  must show both sides under ONE method, never mixing maps across a delta. */
export function commonAttributionMethod(a: ScenarioResult, b: ScenarioResult): AttributionMethod {
  if (
    a.portfolio_pnl.by_factor_conditional_shapley_explicit &&
    b.portfolio_pnl.by_factor_conditional_shapley_explicit
  ) {
    return "conditional_explicit";
  }
  if (
    a.portfolio_pnl.by_factor_conditional_shapley_grouped &&
    b.portfolio_pnl.by_factor_conditional_shapley_grouped
  ) {
    return "conditional_grouped";
  }
  return "naive";
}

export interface ComparisonRow {
  factor: string;
  factorLabel: string;
  shockA: number;
  shockB: number;
  shockDelta: number;
  contribA: number;
  contribB: number;
  contribDelta: number;
}

/** Factor-level A/B/delta rows over the union of both results' shocked or
 *  attributed factors, under one shared attribution method. A side that does
 *  not shock a factor contributes 0. Sorted by |contribution delta| desc. */
export function buildComparisonRows(
  a: ScenarioResult,
  b: ScenarioResult,
  method: AttributionMethod,
  factors?: FactorMetadataMap
): ComparisonRow[] {
  const shocksA = Object.fromEntries(a.factor_shocks.map((fs) => [fs.factor, fs.shock]));
  const shocksB = Object.fromEntries(b.factor_shocks.map((fs) => [fs.factor, fs.shock]));
  const contribsA = selectedFactorAttribution(a, method);
  const contribsB = selectedFactorAttribution(b, method);
  const keys = new Set([
    ...Object.keys(shocksA),
    ...Object.keys(shocksB),
    ...Object.keys(contribsA),
    ...Object.keys(contribsB)
  ]);
  return [...keys]
    .map((factor) => {
      const shockA = shocksA[factor] ?? 0;
      const shockB = shocksB[factor] ?? 0;
      const contribA = contribsA[factor] ?? 0;
      const contribB = contribsB[factor] ?? 0;
      return {
        factor,
        factorLabel: factorDisplayName(factors, factor),
        shockA,
        shockB,
        shockDelta: shockB - shockA,
        contribA,
        contribB,
        contribDelta: contribB - contribA
      };
    })
    .filter(
      (row) =>
        Math.abs(row.shockA) > 1e-9 ||
        Math.abs(row.shockB) > 1e-9 ||
        Math.abs(row.contribA) > 1e-9 ||
        Math.abs(row.contribB) > 1e-9
    )
    .sort((x, y) => Math.abs(y.contribDelta) - Math.abs(x.contribDelta));
}

export interface TickerDelta {
  ticker: string;
  totalA: number | null;
  totalB: number | null;
  delta: number;
}

/** Name-level A/B/delta over the union of both books' tickers. A ticker absent
 *  from one book is null on that side (rendered as an em dash) and treated as 0
 *  in the delta. Sorted by |delta| desc. */
export function buildTickerDeltas(a: ScenarioResult, b: ScenarioResult): TickerDelta[] {
  const mapA = a.portfolio_pnl.by_ticker_total;
  const mapB = b.portfolio_pnl.by_ticker_total;
  const keys = new Set([...Object.keys(mapA), ...Object.keys(mapB)]);
  return [...keys]
    .map((ticker) => {
      const totalA = ticker in mapA ? mapA[ticker] : null;
      const totalB = ticker in mapB ? mapB[ticker] : null;
      return { ticker, totalA, totalB, delta: (totalB ?? 0) - (totalA ?? 0) };
    })
    .sort((x, y) => Math.abs(y.delta) - Math.abs(x.delta));
}

export interface EvidenceGaugeLayer {
  low: number;
  high: number;
  lowPct: number;
  highPct: number;
}

export interface EvidenceGauge {
  base: { value: number; pct: number };
  idio: EvidenceGaugeLayer | null;
  ladder: (EvidenceGaugeLayer & { worst: number; best: number }) | null;
  replay: { min: number; median: number; max: number; minPct: number; medianPct: number; maxPct: number } | null;
}

/** Shared-axis positions (0–100%) for the evidence layers around the base P&L.
 *  Null when the payload carries no layer beyond the point estimate (very old
 *  cached results) — the block renders nothing rather than a bare tick. */
export function buildEvidenceGauge(result: ScenarioResult): EvidenceGauge | null {
  const base = result.portfolio_pnl.total_pnl;
  const unc = result.pnl_uncertainty ?? null;
  const ladder = result.severity_ladder ?? null;
  const replay = result.analog_replay ?? null;
  if (!unc && !ladder && !replay) return null;

  const values = [base];
  if (unc) values.push(base - unc.band_1sigma, base + unc.band_1sigma);
  if (ladder) values.push(ladder.worst_pnl, ladder.best_pnl);
  if (replay) values.push(replay.min_pnl, replay.max_pnl);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  const span = Math.max(hi - lo, 1e-9);
  lo -= span * 0.06;
  hi += span * 0.06;
  const pct = (value: number) => ((value - lo) / (hi - lo)) * 100;

  return {
    base: { value: base, pct: pct(base) },
    idio: unc
      ? {
          low: base - unc.band_1sigma,
          high: base + unc.band_1sigma,
          lowPct: pct(base - unc.band_1sigma),
          highPct: pct(base + unc.band_1sigma)
        }
      : null,
    ladder: ladder
      ? {
          low: ladder.worst_pnl,
          high: ladder.best_pnl,
          worst: ladder.worst_pnl,
          best: ladder.best_pnl,
          lowPct: pct(ladder.worst_pnl),
          highPct: pct(ladder.best_pnl)
        }
      : null,
    replay: replay
      ? {
          min: replay.min_pnl,
          median: replay.median_pnl,
          max: replay.max_pnl,
          minPct: pct(replay.min_pnl),
          medianPct: pct(replay.median_pnl),
          maxPct: pct(replay.max_pnl)
        }
      : null
  };
}

/** Collapsed-state summary for the factor table: "N factors shocked · top {label} {shock}". */
export function summarizeFactorTable(result: ScenarioResult, factors?: FactorMetadataMap): string {
  const shocked = result.factor_shocks.filter((fs) => Math.abs(fs.shock) > 1e-9);
  if (!shocked.length) return "no factor shocks";
  const top = [...shocked].sort((a, b) => Math.abs(b.shock) - Math.abs(a.shock))[0];
  return `${shocked.length} factor${shocked.length === 1 ? "" : "s"} shocked · top ${factorDisplayName(
    factors,
    top.factor
  )} ${formatPercent(top.shock)}`;
}

/** Collapsed-state summary for the name-level table: "N holdings · worst {ticker} {pnl}". */
export function summarizeNameTable(result: ScenarioResult): string {
  const entries = Object.entries(result.portfolio_pnl.by_ticker_total);
  if (!entries.length) return "no holdings";
  const worst = entries.reduce((acc, cur) => (cur[1] < acc[1] ? cur : acc));
  return `${entries.length} holding${entries.length === 1 ? "" : "s"} · worst ${worst[0]} ${formatPercent(
    worst[1]
  )}`;
}
