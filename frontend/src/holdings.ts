import { normalizeTicker } from "./charts";

/** Custom-book form model shared by App (state + run payloads) and the
 * portfolio panel (editor UI). Weight strings stay raw user input — parsing
 * happens at the payload boundary via holdingsFromRows. */

export interface HoldingRow {
  id: string;
  ticker: string;
  weight: string;
}

export type PortfolioMode = "sample" | "custom";
export type ScenarioDraftMode = "sample" | "custom";
export type HoldingUnits = "weights" | "shares";

export const defaultCustomRows: HoldingRow[] = [
  { id: "row-aapl", ticker: "AAPL", weight: "0.5" },
  { id: "row-msft", ticker: "MSFT", weight: "0.5" }
];

export function holdingsFromRows(rows: HoldingRow[]): Record<string, number> {
  const holdings: Record<string, number> = {};
  for (const row of rows) {
    const ticker = normalizeTicker(row.ticker);
    if (!ticker) continue;
    holdings[ticker] = Number(row.weight);
  }
  return holdings;
}

export function parseCsv(text: string): HoldingRow[] {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const dataLines = lines[0]?.toLowerCase().includes("ticker") ? lines.slice(1) : lines;
  return dataLines.map((line, index) => {
    const [ticker, weight] = line.split(",").map((part) => part.trim());
    return {
      id: `csv-${index}-${ticker}`,
      ticker: normalizeTicker(ticker ?? ""),
      weight: weight ?? ""
    };
  });
}
