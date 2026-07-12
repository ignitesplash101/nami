import { useEffect, useMemo, useState } from "react";
import { getTickerMetadata } from "../api";
import { formatPercent, groupByTag } from "../charts";
import { CollapsibleCard } from "../CollapsibleCard";
import { TableScroll } from "../TableScroll";
import type { ScenarioResult, TickerMetadata } from "../types";

export function ExposureBreakdown({ result }: { result: ScenarioResult }) {
  const [meta, setMeta] = useState<TickerMetadata>({});
  const [dimension, setDimension] = useState<"sector" | "country">("sector");
  const tickers = useMemo(() => Object.keys(result.portfolio_holdings), [result]);

  useEffect(() => {
    let cancelled = false;
    getTickerMetadata(tickers)
      .then((m) => {
        if (!cancelled) setMeta(m);
      })
      .catch(() => {
        if (!cancelled) setMeta({});
      });
    return () => {
      cancelled = true;
    };
  }, [tickers]);

  const rows = useMemo(() => groupByTag(result, meta, dimension), [result, meta, dimension]);
  if (!rows.length) return null;

  return (
    <CollapsibleCard
      className="exposure-card"
      eyebrow="Exposure"
      title={`${dimension === "sector" ? "Sector" : "Country"} breakdown`}
      summary={`${rows[0].tag} ${formatPercent(rows[0].weight, 1)} · ${rows.length} ${
        dimension === "sector" ? "sectors" : "countries"
      }`}
      action={
        <div className="segmented" role="radiogroup" aria-label="Exposure dimension">
          <button
            role="radio"
            aria-checked={dimension === "sector"}
            className={dimension === "sector" ? "active" : ""}
            onClick={() => setDimension("sector")}
          >
            Sector
          </button>
          <button
            role="radio"
            aria-checked={dimension === "country"}
            className={dimension === "country" ? "active" : ""}
            onClick={() => setDimension("country")}
          >
            Country
          </button>
        </div>
      }
    >
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>{dimension === "sector" ? "Sector" : "Country"}</th>
              <th className="num">Weight</th>
              <th className="num">Contribution to P&L</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.tag}>
                <td>{row.tag}</td>
                <td className="num">{formatPercent(row.weight, 1)}</td>
                <td className="num">{formatPercent(row.pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
    </CollapsibleCard>
  );
}
