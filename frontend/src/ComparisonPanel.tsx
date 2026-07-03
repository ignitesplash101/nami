import { Download, PinOff } from "lucide-react";
import {
  buildComparisonRows,
  buildTickerDeltas,
  commonAttributionMethod,
  formatPercent
} from "./charts";
import { csvFilename, downloadCsv } from "./csv";
import { TableScroll } from "./TableScroll";
import type { FactorMetadataMap, ScenarioResult, ScenarioRunResponse } from "./types";

const METHOD_LABEL: Record<string, string> = {
  conditional_explicit: "Scenario shocks (explicit-only Conditional Shapley)",
  conditional_grouped: "Group totals (grouped Conditional Shapley)",
  naive: "Naive algebra"
};

function truncate(text: string, max = 140): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function holdingsEqual(a: Record<string, number>, b: Record<string, number>): boolean {
  const keysA = Object.keys(a);
  if (keysA.length !== Object.keys(b).length) return false;
  return keysA.every((key) => b[key] === a[key]);
}

function tone(value: number): string {
  return value < 0 ? "down" : value > 0 ? "up" : "";
}

function SideMeta({ label, result }: { label: string; result: ScenarioResult }) {
  return (
    <div className="comparison-side">
      <p className="readout-eyebrow">{label}</p>
      <p className="comparison-text" title={result.scenario_text}>
        {truncate(result.scenario_text)}
      </p>
      <p className="comparison-side-meta">
        {result.portfolio_name} · as of {result.market_date}
        {result.adjustment_history.length > 0
          ? ` · ${result.adjustment_history.length} adjustment${
              result.adjustment_history.length === 1 ? "" : "s"
            }`
          : ""}
      </p>
    </div>
  );
}

export function ComparisonPanel({
  pinned,
  current,
  factorMeta,
  onUnpin
}: {
  pinned: ScenarioRunResponse;
  current: ScenarioRunResponse;
  factorMeta: FactorMetadataMap;
  onUnpin: () => void;
}) {
  const a = pinned.result;
  const b = current.result;
  const method = commonAttributionMethod(a, b);
  const rows = buildComparisonRows(a, b, method, factorMeta);
  const movers = buildTickerDeltas(a, b).slice(0, 10);
  const totalDelta = b.portfolio_pnl.total_pnl - a.portfolio_pnl.total_pnl;
  const booksDiffer =
    a.portfolio_key !== b.portfolio_key || !holdingsEqual(a.portfolio_holdings, b.portfolio_holdings);
  const asOfDiffers = a.market_date !== b.market_date;

  const exportCsv = () =>
    downloadCsv(
      csvFilename(b.portfolio_name, "comparison", b.market_date, "factor-deltas"),
      [
        "factor",
        "shock_pinned",
        "shock_current",
        "shock_delta",
        "contrib_pinned",
        "contrib_current",
        "contrib_delta"
      ],
      rows.map((row) => [
        row.factorLabel,
        row.shockA,
        row.shockB,
        row.shockDelta,
        row.contribA,
        row.contribB,
        row.contribDelta
      ])
    );

  return (
    <section className="result-card comparison-panel" aria-label="Scenario comparison">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Comparison</p>
          <h3>Pinned vs current</h3>
        </div>
        <button type="button" className="ghost-button" onClick={onUnpin}>
          <PinOff size={14} /> Unpin
        </button>
      </div>

      <div className="comparison-meta">
        <SideMeta label="Pinned" result={a} />
        <SideMeta label="Current" result={b} />
      </div>

      {booksDiffer ? (
        <p className="comparison-warn" role="note">
          Different books — the deltas below mix portfolio composition and scenario effects.
        </p>
      ) : null}
      {asOfDiffers ? (
        <p className="comparison-warn" role="note">
          Different as-of dates ({a.market_date} vs {b.market_date}) — betas and analog registries
          differ by vintage.
        </p>
      ) : null}

      <div className="comparison-headline" aria-label="Comparison headline">
        <div className="comparison-metric">
          <span className="readout-metric-label">Pinned P&L</span>
          <span className={`readout-metric-value ${tone(a.portfolio_pnl.total_pnl)}`}>
            {formatPercent(a.portfolio_pnl.total_pnl)}
          </span>
          {a.pnl_uncertainty ? (
            <span className="comparison-band">
              ± {formatPercent(a.pnl_uncertainty.band_1sigma)} idio (1σ)
            </span>
          ) : null}
        </div>
        <div className="comparison-metric">
          <span className="readout-metric-label">Current P&L</span>
          <span className={`readout-metric-value ${tone(b.portfolio_pnl.total_pnl)}`}>
            {formatPercent(b.portfolio_pnl.total_pnl)}
          </span>
          {b.pnl_uncertainty ? (
            <span className="comparison-band">
              ± {formatPercent(b.pnl_uncertainty.band_1sigma)} idio (1σ)
            </span>
          ) : null}
        </div>
        <div className="comparison-metric">
          <span className="readout-metric-label">Δ (current − pinned)</span>
          <span className={`readout-metric-value ${tone(totalDelta)}`}>
            {formatPercent(totalDelta)}
          </span>
        </div>
      </div>

      <div className="comparison-table-head">
        <h4>Factor shocks and contributions</h4>
        <button
          type="button"
          className="ghost-button table-export-btn"
          onClick={exportCsv}
          aria-label="Export comparison factor deltas as CSV"
          title="Export comparison factor deltas as CSV"
        >
          <Download size={13} /> CSV
        </button>
      </div>
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Factor</th>
              <th className="num">Shock (pinned)</th>
              <th className="num">Shock (current)</th>
              <th className="num">Δ shock</th>
              <th className="num">Contrib (pinned)</th>
              <th className="num">Contrib (current)</th>
              <th className="num">Δ contrib</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.factor}>
                <td>{row.factorLabel}</td>
                <td className="num">{formatPercent(row.shockA)}</td>
                <td className="num">{formatPercent(row.shockB)}</td>
                <td className={`num ${tone(row.shockDelta)}`}>{formatPercent(row.shockDelta)}</td>
                <td className="num">{formatPercent(row.contribA)}</td>
                <td className="num">{formatPercent(row.contribB)}</td>
                <td className={`num ${tone(row.contribDelta)}`}>
                  {formatPercent(row.contribDelta)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
      <p className="hint">
        Both sides shown under {METHOD_LABEL[method]} attribution — one method for the whole
        comparison, never mixed across a delta.
      </p>

      <div className="comparison-table-head">
        <h4>Top name-level movers</h4>
      </div>
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Ticker</th>
              <th className="num">Pinned</th>
              <th className="num">Current</th>
              <th className="num">Δ</th>
            </tr>
          </thead>
          <tbody>
            {movers.map((row) => (
              <tr key={row.ticker}>
                <td>{row.ticker}</td>
                <td className="num">{row.totalA != null ? formatPercent(row.totalA) : "—"}</td>
                <td className="num">{row.totalB != null ? formatPercent(row.totalB) : "—"}</td>
                <td className={`num ${tone(row.delta)}`}>{formatPercent(row.delta)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
      <p className="hint">
        A dash means the ticker is not held in that book (its delta treats the absent side as
        zero). Percent view only — dollar knobs are per-result and would compare unlike NAVs.
      </p>
    </section>
  );
}
