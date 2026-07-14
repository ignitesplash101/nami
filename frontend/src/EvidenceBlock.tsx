import { useRef } from "react";
import {
  buildAnalogReplayRows,
  buildEvidenceGauge,
  formatCurrency,
  formatPercent,
  formatSignedCurrency
} from "./charts";
import { FullscreenButton } from "./FullscreenButton";
import type { AnalogEvent, ScenarioResult } from "./types";
import { useFullscreen } from "./useFullscreen";

/** One "Evidence & bounds" surface replacing the three stacked evidence strips
 *  (±1σ idio framing, analog replay range, severity ladder): every range on a
 *  shared axis, one merged honesty caption (each phrase verbatim), per-analog
 *  rows behind a disclosure. Old cached payloads render whichever layers they
 *  carry; with none, the block renders nothing ("not computed", never zero). */
export function EvidenceBlock({
  result,
  analogEvents,
  showDollars,
  nav,
  currency
}: {
  result: ScenarioResult;
  analogEvents: Record<string, AnalogEvent>;
  showDollars: boolean;
  nav: number | null;
  currency: string;
}) {
  // Hooks called unconditionally, ABOVE the `!gauge` early return below — the
  // gauge is data-dependent (absent on older/thin payloads) and a hook must
  // never be gated by a value computed from props. Note the failure mode is
  // SILENT: a pre-hook early return consumes zero hooks, which React's
  // "Rendered fewer hooks" check cannot detect — it wipes the hook state and
  // orphans effect cleanups instead of throwing (test-pinned).
  const ref = useRef<HTMLElement>(null);
  const fs = useFullscreen(ref, { surface: "evidence and bounds" });
  const gauge = buildEvidenceGauge(result);
  if (!gauge) return null;
  const fmt = (value: number) =>
    showDollars && nav != null
      ? formatSignedCurrency(nav * value, currency)
      : formatPercent(value);
  // Bands are magnitudes — never render them with a sign.
  const fmtAbs = (value: number) =>
    showDollars && nav != null
      ? formatCurrency(nav * Math.abs(value), currency)
      : formatPercent(Math.abs(value));
  const tone = (value: number) => (value < 0 ? "down" : value > 0 ? "up" : "");
  const replayRows = buildAnalogReplayRows(result, analogEvents);
  const ladder = result.severity_ladder;
  const band = result.pnl_uncertainty;

  return (
    <section
      className="evidence-block fullscreen-surface"
      ref={ref}
      aria-label="Evidence and bounds"
    >
      <div className="evidence-head">
        <p className="readout-eyebrow">Evidence &amp; bounds</p>
        <FullscreenButton controller={fs} surface="evidence and bounds" />
      </div>

      <div className="evidence-gauge" aria-hidden="true">
        <span className="evidence-track" />
        {gauge.ladder ? (
          <span
            className="evidence-ladder-bar"
            style={{
              left: `${gauge.ladder.lowPct}%`,
              width: `${Math.max(gauge.ladder.highPct - gauge.ladder.lowPct, 0.5)}%`
            }}
          />
        ) : null}
        {gauge.idio ? (
          <span
            className="evidence-idio-whisker"
            style={{
              left: `${gauge.idio.lowPct}%`,
              width: `${Math.max(gauge.idio.highPct - gauge.idio.lowPct, 0.5)}%`
            }}
          />
        ) : null}
        {gauge.replay ? (
          <>
            <span className="evidence-replay-tick" style={{ left: `${gauge.replay.minPct}%` }} />
            <span
              className="evidence-replay-tick median"
              style={{ left: `${gauge.replay.medianPct}%` }}
            />
            <span className="evidence-replay-tick" style={{ left: `${gauge.replay.maxPct}%` }} />
          </>
        ) : null}
        <span className="evidence-base-tick" style={{ left: `${gauge.base.pct}%` }} />
      </div>

      <ul className="evidence-rows">
        <li>
          <span className="evidence-row-label">
            <span className="evidence-swatch base" aria-hidden="true" /> Scenario (base)
          </span>
          <span className={`evidence-row-value ${tone(gauge.base.value)}`}>
            {fmt(gauge.base.value)}
          </span>
        </li>
        {band ? (
          <li>
            <span className="evidence-row-label">
              <span className="evidence-swatch idio" aria-hidden="true" /> ±1σ idio dispersion
            </span>
            <span className="evidence-row-value">± {fmtAbs(band.band_1sigma)}</span>
          </li>
        ) : null}
        {ladder ? (
          <li>
            <span className="evidence-row-label">
              <span className="evidence-swatch ladder" aria-hidden="true" /> Envelope bounds
              <span className="evidence-row-note">
                {ladder.n_banded} banded{ladder.n_held > 0 ? ` · ${ladder.n_held} held` : ""}
              </span>
            </span>
            <span className="evidence-row-value">
              <span className={tone(ladder.worst_pnl)}>{fmt(ladder.worst_pnl)}</span>
              {" to "}
              <span className={tone(ladder.best_pnl)}>{fmt(ladder.best_pnl)}</span>
            </span>
          </li>
        ) : null}
        {gauge.replay && replayRows ? (
          <li>
            <span className="evidence-row-label">
              <span className="evidence-swatch replay" aria-hidden="true" /> Analog replay
              <span className="evidence-row-note">{replayRows.length} analogs</span>
            </span>
            <span className="evidence-row-value">
              <span className={tone(gauge.replay.min)}>{fmt(gauge.replay.min)}</span>
              {replayRows.length > 2 ? (
                <> / median {fmt(gauge.replay.median)}</>
              ) : null}
              {" to "}
              <span className={tone(gauge.replay.max)}>{fmt(gauge.replay.max)}</span>
            </span>
          </li>
        ) : null}
      </ul>

      {replayRows && replayRows.length ? (
        <details className="evidence-analogs">
          <summary>Per-analog replay detail ({replayRows.length})</summary>
          <ul className="replay-events">
            {replayRows.map((row) => (
              <li key={row.eventId}>
                <span className="replay-event-name">{row.name}</span>
                <span className={`replay-event-pnl ${tone(row.pnl)}`}>{fmt(row.pnl)}</span>
                <span className="replay-coverage">
                  {row.covered}/{row.total} factors
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <p className="replay-caption">
        {band
          ? "The ±1σ idiosyncratic band is a dispersion floor — not a confidence interval. "
          : ""}
        {ladder
          ? "Envelope bounds push each banded shock to its adverse (or favorable) analog-envelope edge — an evidence-base bound, not a joint scenario. "
          : ""}
        {gauge.replay
          ? "Analog rows push each selected event's realized factor moves through this book's current betas — historical replay, not a forecast."
          : ""}
      </p>
    </section>
  );
}
