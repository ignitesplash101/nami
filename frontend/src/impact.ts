import { selectedFactorAttribution } from "./charts";
import { FALLBACK_FACTORS, factorDisplayName } from "./factors";
import type {
  AnalogEvent,
  AttributionMethod,
  FactorMetadataMap,
  ScenarioResult
} from "./types";

/* Semantic models for the two "how the scenario lands" charts: the Drivers
 * transmission rows (scenario move → P&L effect, per factor and per single
 * name) and the Positions holding-impact rows. Every position is a 0–100
 * percent of its own track so the components stay plain token CSS — no chart
 * runtime on the first screen. Values are never re-derived here: contribution
 * comes from the SAME attribution map the waterfall uses, and shocks come from
 * the result verbatim. */

const EPSILON = 1e-6;
const STRIP_PADDING = 0.1;
const IMPACT_PADDING = 0.04;

const GROUP_LABELS: Record<string, string> = {
  market: "Market",
  sector: "Sector",
  style: "Style",
  macro: "Macro"
};

export interface AnalogMove {
  eventId: string;
  name: string;
  value: number;
  pct: number;
}

export interface TransmissionRow {
  id: string;
  kind: "factor" | "single-name";
  key: string;
  label: string;
  groupLabel: string;
  /** The move the scenario applies (decimal return of the factor series). */
  shock: number;
  /** Contribution to portfolio P&L (decimal), from the main attribution map. */
  contribution: number;
  reasoning: string;
  /** Realized move of this factor in each selected analog event, in selection order. */
  analogs: AnalogMove[];
  /** Analog-envelope p10–p90 band; null when the evidence is thin (count < 3) or absent. */
  range: { low: number; high: number; lowPct: number; highPct: number; count: number } | null;
  strip: { zeroPct: number; shockPct: number };
  impact: { leftPct: number; widthPct: number };
  /** Where the scenario move sits against the analog moves, for the plain-language cue. */
  severity: "beyond" | "within" | "none";
}

export interface TransmissionModel {
  rows: TransmissionRow[];
  impactZeroPct: number;
  factorTotal: number;
  singleNameTotal: number;
  total: number;
  /** total − (factors + single names); non-zero only on legacy payloads that do not reconcile. */
  residual: number;
  analogCount: number;
}

function pctOf(value: number, lo: number, hi: number): number {
  if (hi - lo <= 0) return 50;
  return Math.min(100, Math.max(0, ((value - lo) / (hi - lo)) * 100));
}

function paddedDomain(values: number[], padding: number): [number, number] {
  const finite = values.filter(Number.isFinite);
  let lo = Math.min(0, ...finite);
  let hi = Math.max(0, ...finite);
  if (hi - lo < EPSILON) {
    lo = -0.01;
    hi = 0.01;
  }
  const span = hi - lo;
  return [lo - span * padding, hi + span * padding];
}

function factorGroupLabel(factors: FactorMetadataMap | undefined, factor: string): string {
  const group = factors?.[factor]?.group ?? FALLBACK_FACTORS[factor]?.group;
  return group ? GROUP_LABELS[group] ?? group : "Factor";
}

/** Rows for the scenario → P&L transmission chart, largest |contribution| first.
 * Fails closed (null) on non-finite inputs so the caller can fall back to the
 * factor table instead of drawing a misleading chart. */
export function buildTransmissionModel(
  result: ScenarioResult,
  method: AttributionMethod,
  factors?: FactorMetadataMap,
  analogEvents?: Record<string, AnalogEvent> | null
): TransmissionModel | null {
  const byFactor = selectedFactorAttribution(result, method);
  const periphery = result.portfolio_pnl.by_ticker_periphery;
  const total = result.portfolio_pnl.total_pnl;
  const shocks = new Map(result.factor_shocks.map((shock) => [shock.factor, shock]));
  if (
    !Number.isFinite(total) ||
    !Object.values(byFactor).every(Number.isFinite) ||
    !Object.values(periphery).every(Number.isFinite) ||
    !result.factor_shocks.every((shock) => Number.isFinite(shock.shock))
  ) {
    return null;
  }

  const analogReturns = result.analog_event_returns ?? [];
  const factorKeys = new Set<string>([
    ...result.factor_shocks.map((shock) => shock.factor),
    ...Object.keys(byFactor)
  ]);

  type Draft = Omit<TransmissionRow, "strip" | "impact" | "severity" | "analogs" | "range"> & {
    analogValues: { eventId: string; name: string; value: number }[];
    envelope: { p10: number; p90: number; count: number } | null;
  };
  const drafts: Draft[] = [];

  for (const factor of factorKeys) {
    const shock = shocks.get(factor)?.shock ?? 0;
    const contribution = byFactor[factor] ?? 0;
    if (Math.abs(shock) <= EPSILON && Math.abs(contribution) <= EPSILON) continue;
    const analogValues = analogReturns.flatMap((entry) => {
      const value = entry.factor_returns[factor];
      return typeof value === "number" && Number.isFinite(value)
        ? [{ eventId: entry.event_id, name: analogEvents?.[entry.event_id]?.name ?? entry.event_id, value }]
        : [];
    });
    const env = result.factor_envelope[factor];
    const envelope =
      env &&
      Number.isFinite(env.p10) &&
      Number.isFinite(env.p90) &&
      Number.isFinite(env.count) &&
      env.count >= 3
        ? { p10: env.p10, p90: env.p90, count: env.count }
        : null;
    drafts.push({
      id: `factor:${factor}`,
      kind: "factor",
      key: factor,
      label: factorDisplayName(factors, factor),
      groupLabel: factorGroupLabel(factors, factor),
      shock,
      contribution,
      reasoning: shocks.get(factor)?.reasoning ?? "",
      analogValues,
      envelope
    });
  }

  const peripheryShocks = new Map(result.periphery_shocks.map((shock) => [shock.ticker, shock]));
  const singleNames = new Set<string>([...peripheryShocks.keys(), ...Object.keys(periphery)]);
  for (const ticker of singleNames) {
    const contribution = periphery[ticker] ?? 0;
    if (Math.abs(contribution) <= EPSILON) continue;
    const shock = peripheryShocks.get(ticker);
    drafts.push({
      id: `single:${ticker}`,
      kind: "single-name",
      key: ticker,
      label: ticker,
      groupLabel: "Single name",
      shock: shock?.shock ?? 0,
      contribution,
      reasoning: shock?.reasoning ?? "",
      analogValues: [],
      envelope: null
    });
  }

  drafts.sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));

  const [impactLo, impactHi] = paddedDomain(
    drafts.map((draft) => draft.contribution),
    IMPACT_PADDING
  );
  const impactZeroPct = pctOf(0, impactLo, impactHi);

  // Rows with no history to scale against (single names, uncovered factors)
  // share ONE strip domain, so a -4% and a -8% shock never draw identically.
  const historyless = drafts
    .filter((draft) => !draft.analogValues.length && !draft.envelope)
    .map((draft) => draft.shock);
  const historylessDomain = paddedDomain(historyless, STRIP_PADDING);

  const rows: TransmissionRow[] = drafts.map(({ analogValues, envelope, ...draft }) => {
    const [lo, hi] =
      !analogValues.length && !envelope
        ? historylessDomain
        : paddedDomain(
            [
              draft.shock,
              ...analogValues.map((analog) => analog.value),
              ...(envelope ? [envelope.p10, envelope.p90] : [])
            ],
            STRIP_PADDING
          );
    const valuePct = pctOf(draft.contribution, impactLo, impactHi);
    const analogMin = Math.min(...analogValues.map((analog) => analog.value));
    const analogMax = Math.max(...analogValues.map((analog) => analog.value));
    const severity: TransmissionRow["severity"] =
      analogValues.length < 2 || Math.abs(draft.shock) <= EPSILON
        ? "none"
        : draft.shock < analogMin - EPSILON || draft.shock > analogMax + EPSILON
          ? "beyond"
          : "within";
    return {
      ...draft,
      analogs: analogValues.map((analog) => ({ ...analog, pct: pctOf(analog.value, lo, hi) })),
      range: envelope
        ? {
            low: envelope.p10,
            high: envelope.p90,
            lowPct: pctOf(envelope.p10, lo, hi),
            highPct: pctOf(envelope.p90, lo, hi),
            count: envelope.count
          }
        : null,
      strip: { zeroPct: pctOf(0, lo, hi), shockPct: pctOf(draft.shock, lo, hi) },
      impact: {
        leftPct: Math.min(valuePct, impactZeroPct),
        widthPct: Math.abs(valuePct - impactZeroPct)
      },
      severity
    };
  });

  const factorTotal = drafts
    .filter((draft) => draft.kind === "factor")
    .reduce((sum, draft) => sum + draft.contribution, 0);
  const singleNameTotal = Object.values(periphery).reduce((sum, value) => sum + value, 0);
  const residual = total - factorTotal - singleNameTotal;

  return {
    rows,
    impactZeroPct,
    factorTotal,
    singleNameTotal,
    total,
    residual: Math.abs(residual) > EPSILON ? residual : 0,
    analogCount: analogReturns.length
  };
}

export interface HoldingImpactRow {
  ticker: string;
  weight: number;
  /** Contribution to portfolio P&L (decimal): weight × the name's scenario return. */
  total: number;
  factorPart: number;
  singleNamePart: number;
  /** The name's own modeled move (total / weight); null for a zero-weight row. */
  ownMove: number | null;
  bar: { leftPct: number; widthPct: number };
  /** Share of the bar drawn as the company-specific segment (0–100), same-sign only. */
  singleNameSharePct: number;
}

export interface HoldingImpactModel {
  rows: HoldingImpactRow[];
  zeroPct: number;
}

/** Holdings ranked by |contribution to P&L| on one shared axis. */
export function buildHoldingImpactModel(result: ScenarioResult): HoldingImpactModel | null {
  const pnl = result.portfolio_pnl;
  const tickers = Object.keys(pnl.by_ticker_total);
  const values = tickers.map((ticker) => pnl.by_ticker_total[ticker]);
  if (!tickers.length || !values.every(Number.isFinite)) return null;
  const [lo, hi] = paddedDomain(values, IMPACT_PADDING);
  const zeroPct = pctOf(0, lo, hi);
  const rows = tickers
    .map((ticker) => {
      const total = pnl.by_ticker_total[ticker] ?? 0;
      const factorPart = pnl.by_ticker_factor[ticker] ?? 0;
      const singleNamePart = pnl.by_ticker_periphery[ticker] ?? 0;
      const weight = result.portfolio_holdings[ticker] ?? 0;
      const valuePct = pctOf(total, lo, hi);
      const sameSign =
        Math.abs(total) > EPSILON && Math.sign(singleNamePart) === Math.sign(total);
      return {
        ticker,
        weight,
        total,
        factorPart,
        singleNamePart,
        ownMove: Math.abs(weight) > EPSILON ? total / weight : null,
        bar: { leftPct: Math.min(valuePct, zeroPct), widthPct: Math.abs(valuePct - zeroPct) },
        singleNameSharePct: sameSign
          ? Math.min(100, (Math.abs(singleNamePart) / Math.abs(total)) * 100)
          : 0
      };
    })
    .sort((a, b) => Math.abs(b.total) - Math.abs(a.total));
  return { rows, zeroPct };
}
