import type { ScenarioResult } from "./types";

/** Pure hydration of a composer draft from any completed/saved result — the
 * fix for the saved-scenario dead-end (saved results carry no cache_key, so the
 * Adjust tab is absent). No React imports: App supplies context, this decides,
 * App applies. Deliberately does NOT resurrect cache_keys — the GCS cache has a
 * 7-day TTL, so adjust-on-saved would be a 410 trap; full-state re-run is the
 * durable iteration path. */

export interface RerunHoldingRow {
  ticker: string;
  weight: number;
}

export interface RerunDraftSample {
  mode: "sample";
  key: string;
}

export interface RerunDraftCustom {
  mode: "custom";
  name: string;
  rows: RerunHoldingRow[];
  // Always weights: a rebuilt book is weight-based even when the source was
  // Shares/MTM (see sharesConversion) — we never resurrect share counts.
  units: "weights";
}

export type RerunDraftPortfolio = RerunDraftSample | RerunDraftCustom;

export type RerunAsOf = { kind: "live" } | { kind: "backdated"; date: string };

export interface RerunDraft {
  scenarioText: string;
  portfolio: RerunDraftPortfolio;
  benchmark: string | null;
  asOf: RerunAsOf;
  // True only when the draft requires admin AND the session lacks it — the
  // caller shows an unlock prompt and stops rather than partially hydrating.
  needsAdmin: boolean;
  needsAdminReason: string;
  // Source was Shares/MTM mode; the caller discloses the weight-based re-run.
  sharesConversion: boolean;
  // Notional value pass-through so the dollar view survives the re-run.
  nav: number | null;
}

export interface RerunDraftContext {
  // The set of live sample-portfolio keys, so a recognized key restores as a
  // sample selection and an unrecognized one ("custom", a removed/renamed key,
  // a snapshot-derived book) rebuilds from holdings.
  sampleKeys: string[];
  isAdmin: boolean;
}

export function buildRerunDraft(result: ScenarioResult, ctx: RerunDraftContext): RerunDraft {
  const isSample = ctx.sampleKeys.includes(result.portfolio_key);
  const portfolio: RerunDraftPortfolio = isSample
    ? { mode: "sample", key: result.portfolio_key }
    : {
        mode: "custom",
        name: result.portfolio_name || "Custom Book",
        rows: Object.entries(result.portfolio_holdings).map(([ticker, weight]) => ({
          ticker,
          weight
        })),
        units: "weights"
      };

  // narrative_mode — not a date comparison — is the reliable backdated signal:
  // a live run records "grounded" and keeps its own day's close as
  // requested_as_of_date, which is in the PAST when the saved run is reopened
  // later, so comparing that date against the current live anchor / today would
  // mis-flag every reopened live scenario as backdated. A backdated run records
  // "analog_only" and the requested date is the one to restore.
  const isBackdated =
    result.narrative_mode === "analog_only" && result.requested_as_of_date != null;
  const asOf: RerunAsOf = isBackdated
    ? { kind: "backdated", date: result.requested_as_of_date as string }
    : { kind: "live" };

  const reasons: string[] = [];
  if (portfolio.mode === "custom") reasons.push("custom portfolio");
  if (isBackdated) reasons.push("backdated as-of date");
  const needsAdmin = reasons.length > 0 && !ctx.isAdmin;

  return {
    scenarioText: result.scenario_text,
    portfolio,
    benchmark: result.benchmark_ticker ?? null,
    asOf,
    needsAdmin,
    needsAdminReason: needsAdmin ? reasons.join(" and ") : "",
    sharesConversion: result.position_quantities != null,
    nav: result.portfolio_nav ?? null
  };
}
