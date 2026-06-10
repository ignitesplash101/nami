// Shared display formatters. charts.ts keeps its original chart-oriented
// formatters (formatPercent / formatCurrency / formatSignedCurrency / parseNav /
// normalizeTicker); this module holds everything that used to be ad-hoc at
// call sites so number/date rendering stays consistent across tables.

const EM_DASH = "—";

/** Share counts: thousands separators, at most 2 decimals. null/undefined → "—". */
export function formatShares(value: number | null | undefined): string {
  if (value == null) return EM_DASH;
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/** Mark price in its native quote unit; optional currency suffix. null → "—". */
export function formatMarkPrice(
  value: number | null | undefined,
  currency?: string | null
): string {
  if (value == null) return EM_DASH;
  const number = value.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return currency ? `${number} ${currency}` : number;
}

/** FX rate to USD at 4 significant figures: formatFxRate("JPY", 0.0064516) → "JPY 0.006452". */
export function formatFxRate(pair: string, rate: number): string {
  return `${pair} ${rate.toPrecision(4)}`;
}

/** Absolute timestamp for history rows, date included ("Jun 10, 2026, 2:32 PM"). */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit"
  });
}

/** Relative age ("just now" / "5m ago" / "3h ago" / "3d ago" / locale date >30d).
 * `now` injectable for deterministic tests. */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const ms = now - new Date(iso).getTime();
  const minutes = Math.floor(ms / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

/** Risk-diagnostic evidence numbers — fixed 4dp, matching the table's density. */
export function formatEvidence(value: number): string {
  return value.toFixed(4);
}

/** Filesystem-safe slug: lowercase, non-alphanumerics → "-", capped at `maxWords`. */
export function slugify(text: string, maxWords = 5): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "")
    .split("-")
    .filter(Boolean)
    .slice(0, maxWords)
    .join("-");
}
