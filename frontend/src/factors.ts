import type { FactorMetadata, FactorMetadataMap } from "./types";

export const FALLBACK_FACTORS: FactorMetadataMap = {
  SPY: {
    key: "SPY",
    ticker: "SPY",
    group: "market",
    short_label: "US large-cap",
    display_name: "US large-cap equities",
    description: "S&P 500 ETF; weekly % return."
  },
  ACWI: {
    key: "ACWI",
    ticker: "ACWI",
    group: "market",
    short_label: "Global equities",
    display_name: "Global equities",
    description: "MSCI All Country World ETF; weekly % return."
  },
  XLK: label("XLK", "sector", "US technology", "US technology"),
  XLF: label("XLF", "sector", "US financials", "US financials"),
  XLE: label("XLE", "sector", "US energy", "US energy"),
  XLV: label("XLV", "sector", "US health care", "US health care"),
  XLI: label("XLI", "sector", "US industrials", "US industrials"),
  XLY: label("XLY", "sector", "US discretionary", "US consumer discretionary"),
  XLP: label("XLP", "sector", "US staples", "US consumer staples"),
  XLU: label("XLU", "sector", "US utilities", "US utilities"),
  XLB: label("XLB", "sector", "US materials", "US materials"),
  XLRE: label("XLRE", "sector", "US real estate", "US real estate"),
  XLC: label("XLC", "sector", "US comm services", "US communication services"),
  MTUM: label("MTUM", "style", "Momentum", "Momentum stocks"),
  QUAL: label("QUAL", "style", "Quality", "Quality stocks"),
  VLUE: label("VLUE", "style", "Value", "Value stocks"),
  SIZE: label("SIZE", "style", "Small-cap tilt", "Small-cap tilt"),
  USMV: label("USMV", "style", "Low volatility", "Low-volatility stocks"),
  TNX: label("TNX", "macro", "US 10Y yield", "US 10Y yield", "^TNX"),
  DXY: label("DXY", "macro", "US dollar", "US dollar", "DX-Y.NYB"),
  VIX: label("VIX", "macro", "Equity volatility", "Equity volatility", "^VIX"),
  OIL: label("OIL", "macro", "Oil price", "Oil price", "CL=F")
};

function label(
  key: string,
  group: FactorMetadata["group"],
  shortLabel: string,
  displayName: string,
  ticker = key
): FactorMetadata {
  return {
    key,
    ticker,
    group,
    short_label: shortLabel,
    display_name: displayName,
    description: displayName
  };
}

export function factorMap(items: FactorMetadata[]): FactorMetadataMap {
  return {
    ...FALLBACK_FACTORS,
    ...Object.fromEntries(items.map((item) => [item.key, item]))
  };
}

export function factorDisplayName(
  factors: FactorMetadataMap | undefined,
  key: string,
  variant: "full" | "short" = "full"
): string {
  const meta = factors?.[key] ?? FALLBACK_FACTORS[key];
  if (!meta) return key;
  const labelText = variant === "short" ? meta.short_label : meta.display_name;
  return `${labelText} (${key})`;
}

export function factorDescription(factors: FactorMetadataMap | undefined, key: string): string {
  const meta = factors?.[key] ?? FALLBACK_FACTORS[key];
  if (!meta) return key;
  return `${meta.display_name} (${key}); market data ticker ${meta.ticker}. ${meta.description}`;
}
