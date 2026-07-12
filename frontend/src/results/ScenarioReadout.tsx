import {
  buildReadout,
  formatCurrency,
  formatPercent,
  formatSignedCurrency
} from "../charts";
import { GLOSSARY } from "../copy/glossary";
import { InfoTip } from "../copy/InfoTip";
import type { AttributionMethod, FactorMetadataMap, ScenarioResult } from "../types";

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
  const pnlText =
    showDollars && nav != null
      ? formatSignedCurrency(nav * readout.totalPnl, currency)
      : formatPercent(readout.totalPnl);
  const activeReturnText =
    readout.activeReturn != null && showDollars && nav != null
      ? `${formatSignedCurrency(nav * readout.activeReturn, currency)} (${formatPercent(
          readout.activeReturn
        )})`
      : readout.activeReturn != null
        ? formatPercent(readout.activeReturn)
        : null;
  const toneClass =
    readout.direction === "gain" ? "up" : readout.direction === "loss" ? "down" : "flat";
  return (
    <section className={`scenario-readout ${toneClass}`} aria-label="Impact summary">
      <p className="readout-eyebrow">Impact summary</p>
      <p className="readout-headline">{readout.headline}</p>
      <div className="readout-metrics">
        <div>
          <span className="readout-metric-label">Portfolio P&amp;L</span>
          <span className={`readout-metric-value ${toneClass}`}>{pnlText}</span>
          {readout.idioBand != null ? (
            <span className="readout-idio-band">
              ±{" "}
              {showDollars && nav != null
                ? formatCurrency(nav * readout.idioBand, currency)
                : formatPercent(readout.idioBand)}{" "}
              single-name noise
              <InfoTip label="About single-name noise">
                {GLOSSARY.singleNameNoise.plain} {GLOSSARY.singleNameNoise.detail}
              </InfoTip>
            </span>
          ) : null}
        </div>
        <div>
          <span className="readout-metric-label">Top driver</span>
          <span className="readout-metric-value">
            {readout.topFactor} ({formatPercent(readout.topContribution)})
          </span>
        </div>
        {readout.activeReturn != null && readout.benchmarkTicker ? (
          <div>
            <span className="readout-metric-label">Active vs {readout.benchmarkTicker}</span>
            <span className="readout-metric-value">{activeReturnText}</span>
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
    </section>
  );
}
