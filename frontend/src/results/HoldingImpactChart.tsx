import { useState } from "react";
import { formatPercent, formatSignedCurrency } from "../charts";
import type { HoldingImpactModel } from "../impact";

function signedPercent(value: number, digits = 2): string {
  return `${value > 0 ? "+" : ""}${formatPercent(value, digits)}`;
}

/** Holdings ranked by their contribution to portfolio P&L on one shared axis.
 * The lighter segment is the company-specific part of the bar (drawn only when
 * it has the same sign as the total); the name's own modeled move rides beside
 * its weight so "big position, small move" and "small position, big move" read
 * differently. Token CSS only — no chart runtime. */
export function HoldingImpactChart({
  model,
  showDollars,
  nav,
  currency,
  initialRows
}: {
  model: HoldingImpactModel;
  showDollars: boolean;
  nav: number | null;
  currency: string;
  initialRows: number;
}) {
  const [showAll, setShowAll] = useState(false);
  const dollars = showDollars && nav != null;
  const fmt = (value: number) =>
    dollars ? formatSignedCurrency(value * (nav ?? 0), currency) : signedPercent(value);
  const visible = showAll ? model.rows : model.rows.slice(0, initialRows);
  const hiddenCount = model.rows.length - visible.length;
  const anySingleName = model.rows.some((row) => row.singleNameSharePct > 0);

  return (
    <div className="holding-impact-chart" role="group" aria-label="Holdings ranked by effect on P&L">
      <ol className="holding-impact-rows">
        {visible.map((row) => (
          <li
            key={row.ticker}
            className="holding-impact-row"
            aria-label={`${row.ticker}: ${formatPercent(row.weight, 1)} of the book${
              row.ownMove != null ? `, modeled move ${signedPercent(row.ownMove, 1)}` : ""
            }; effect on P&L ${fmt(row.total)}`}
          >
            <span className="holding-impact-name" aria-hidden="true">
              <strong>{row.ticker}</strong>
              <span className="holding-impact-meta">
                {formatPercent(row.weight, 1)} weight
                {row.ownMove != null ? ` · moves ${signedPercent(row.ownMove, 1)}` : ""}
              </span>
            </span>
            <span className="holding-impact-track" aria-hidden="true">
              <span className="holding-impact-zero" style={{ left: `${model.zeroPct}%` }} />
              <span
                className={`holding-impact-bar ${row.total < 0 ? "down" : "up"}`}
                style={{
                  left: `${row.bar.leftPct}%`,
                  width: `${Math.max(row.bar.widthPct, 0.4)}%`
                }}
              >
                {row.singleNameSharePct > 0 ? (
                  <span
                    className="holding-impact-single"
                    style={{ width: `${row.singleNameSharePct}%` }}
                  />
                ) : null}
              </span>
            </span>
            <span className="holding-impact-value" aria-hidden="true">
              {fmt(row.total)}
            </span>
          </li>
        ))}
      </ol>
      <div className="holding-impact-foot">
        {anySingleName ? (
          <span className="tx-key">
            <span className="holding-impact-key" aria-hidden="true" /> Company-specific part
          </span>
        ) : null}
        {hiddenCount > 0 || showAll ? (
          <button
            type="button"
            className="ghost-button tx-more"
            aria-expanded={showAll}
            onClick={() => setShowAll((value) => !value)}
          >
            {showAll ? "Show the largest only" : `Show all ${model.rows.length} holdings`}
          </button>
        ) : null}
      </div>
    </div>
  );
}
