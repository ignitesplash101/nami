import {
  buildReadout,
  formatCurrency,
  formatPercent,
  formatSignedCurrency
} from "../charts";
import { GLOSSARY } from "../copy/glossary";
import { InfoTip } from "../copy/InfoTip";
import type { AttributionMethod, FactorMetadataMap, ScenarioResult } from "../types";

function signedPercent(value: number): string {
  return `${value > 0 ? "+" : ""}${formatPercent(value)}`;
}

export function ScenarioReadout({
  result,
  attributionMethod,
  factorMeta,
  showDollars,
  nav,
  currency
}: {
  result: ScenarioResult;
  attributionMethod: AttributionMethod;
  factorMeta: FactorMetadataMap;
  showDollars: boolean;
  nav: number | null;
  currency: string;
}) {
  const readout = buildReadout(result, attributionMethod, factorMeta);
  const dollars = showDollars && nav != null;
  // The hero carries the selected unit; the line under it carries the other
  // unit whenever a NAV exists, so switching units never hides a number.
  const pnlText = dollars
    ? formatSignedCurrency((nav ?? 0) * readout.totalPnl, currency)
    : signedPercent(readout.totalPnl);
  const pnlAltText = dollars
    ? `${signedPercent(readout.totalPnl)} of the portfolio`
    : nav != null
      ? `${formatSignedCurrency(nav * readout.totalPnl, currency)} on ${formatCurrency(nav, currency)}`
      : null;
  const fmtEffect = (value: number) =>
    dollars ? formatSignedCurrency((nav ?? 0) * value, currency) : signedPercent(value);
  const toneClass =
    readout.direction === "gain" ? "up" : readout.direction === "loss" ? "down" : "flat";
  return (
    <section className={`scenario-readout ${toneClass}`} aria-label="Impact summary">
      <p className="readout-eyebrow">Impact summary</p>
      <p className="readout-headline">{readout.headline}</p>
      <div className="readout-body">
        <div className="readout-hero">
          <span className="readout-metric-label">Portfolio P&amp;L</span>
          <span className={`readout-hero-value ${toneClass}`}>{pnlText}</span>
          {pnlAltText ? <span className="readout-hero-alt">{pnlAltText}</span> : null}
          {readout.idioBand != null ? (
            <span className="readout-idio-band">
              ±{" "}
              {dollars
                ? formatCurrency((nav ?? 0) * readout.idioBand, currency)
                : formatPercent(readout.idioBand)}{" "}
              single-name noise
              <InfoTip label="About single-name noise">
                {GLOSSARY.singleNameNoise.plain} {GLOSSARY.singleNameNoise.detail}
              </InfoTip>
            </span>
          ) : null}
        </div>
        <div className="readout-metrics">
          <div>
            <span className="readout-metric-label">Top driver</span>
            <span className="readout-metric-value">{readout.topFactor}</span>
            <span className="readout-metric-sub">
              {fmtEffect(readout.topContribution)} of the P&amp;L
            </span>
          </div>
          {readout.activeReturn != null && readout.benchmarkTicker ? (
            <div>
              <span className="readout-metric-label">Active vs {readout.benchmarkTicker}</span>
              <span className="readout-metric-value">{fmtEffect(readout.activeReturn)}</span>
              <span className="readout-metric-sub">
                {dollars ? signedPercent(readout.activeReturn) : "relative to the benchmark"}
              </span>
            </div>
          ) : null}
          <div>
            <span className="readout-metric-label">Evidence</span>
            <span className="readout-metric-value">
              {readout.analogCount} historical events · {readout.citationCount} sources
              <InfoTip label="About the evidence">{GLOSSARY.historicalEvents.plain}</InfoTip>
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}
