import { useRef } from "react";
import type { ReactNode } from "react";
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
  const fmtTick = (value: number) =>
    showDollars && nav != null
      ? compactCurrency(nav * value, currency)
      : `${value > 0 ? "+" : ""}${Number((value * 100).toFixed(1))}%`;
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

      <ul className="evidence-rows">
        <li>
          <span className="evidence-row-label">
            <span className="evidence-swatch base" aria-hidden="true" /> Scenario (base)
          </span>
          <EvidenceTrack zeroPct={gauge.zero.pct} basePct={gauge.base.pct}>
            <span className="evidence-point" style={{ left: `${gauge.base.pct}%` }} />
          </EvidenceTrack>
          <span className={`evidence-row-value ${tone(gauge.base.value)}`}>
            {fmt(gauge.base.value)}
          </span>
        </li>
        {band && gauge.idio ? (
          <li>
            <span className="evidence-row-label">
              <span className="evidence-swatch idio" aria-hidden="true" /> ±1σ idio dispersion
            </span>
            <EvidenceTrack zeroPct={gauge.zero.pct} basePct={gauge.base.pct}>
              <span
                className="evidence-whisker"
                style={{
                  left: `${gauge.idio.lowPct}%`,
                  width: `${Math.max(gauge.idio.highPct - gauge.idio.lowPct, 0.5)}%`
                }}
              />
            </EvidenceTrack>
            <span className="evidence-row-value">± {fmtAbs(band.band_1sigma)}</span>
          </li>
        ) : null}
        {ladder && gauge.ladder ? (
          <li className="is-range">
            <span className="evidence-row-label">
              <span className="evidence-swatch ladder" aria-hidden="true" /> Envelope bounds
              <span className="evidence-row-note">
                {ladder.n_banded} banded{ladder.n_held > 0 ? ` · ${ladder.n_held} held` : ""}
              </span>
            </span>
            <EvidenceTrack zeroPct={gauge.zero.pct} basePct={gauge.base.pct}>
              <span
                className="evidence-band"
                style={{
                  left: `${gauge.ladder.lowPct}%`,
                  width: `${Math.max(gauge.ladder.highPct - gauge.ladder.lowPct, 0.5)}%`
                }}
              />
            </EvidenceTrack>
            <span className="evidence-row-value">
              <span className={tone(ladder.worst_pnl)}>{fmt(ladder.worst_pnl)}</span>
              {" to "}
              <span className={tone(ladder.best_pnl)}>{fmt(ladder.best_pnl)}</span>
            </span>
          </li>
        ) : null}
        {gauge.replay && replayRows ? (
          <li className="is-range">
            <span className="evidence-row-label">
              <span className="evidence-swatch replay" aria-hidden="true" /> Analog replay
              <span className="evidence-row-note">{replayRows.length} analogs</span>
            </span>
            <EvidenceTrack zeroPct={gauge.zero.pct} basePct={gauge.base.pct}>
              <span
                className="evidence-span"
                style={{
                  left: `${gauge.replay.minPct}%`,
                  width: `${Math.max(gauge.replay.maxPct - gauge.replay.minPct, 0.5)}%`
                }}
              />
              {replayRows.length > 2 ? (
                <span className="evidence-median" style={{ left: `${gauge.replay.medianPct}%` }} />
              ) : null}
              {gauge.replay.events.map((event) => (
                <span
                  key={event.eventId}
                  className="evidence-event"
                  style={{ left: `${event.pct}%` }}
                  title={`${
                    replayRows.find((row) => row.eventId === event.eventId)?.name ?? event.eventId
                  }: ${fmt(event.value)}`}
                />
              ))}
            </EvidenceTrack>
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
        {gauge.ticks.length ? (
          <li className="evidence-axis" aria-hidden="true">
            <span />
            <span className="evidence-axis-ticks">
              {gauge.ticks.map((tick) => (
                <span
                  key={tick.value}
                  className={tick.value === 0 ? "is-zero" : undefined}
                  style={{ left: `${tick.pct}%` }}
                >
                  {fmtTick(tick.value)}
                </span>
              ))}
            </span>
            <span />
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

/** One shared-axis track: zero and the scenario base are drawn on every row so
 * the eye can run a straight line from the point estimate through each range. */
function EvidenceTrack({
  zeroPct,
  basePct,
  children
}: {
  zeroPct: number;
  basePct: number;
  children: ReactNode;
}) {
  return (
    <span className="evidence-track" aria-hidden="true">
      <span className="evidence-track-axis" />
      <span className="evidence-zero" style={{ left: `${zeroPct}%` }} />
      {children}
      <span className="evidence-base-guide" style={{ left: `${basePct}%` }} />
    </span>
  );
}

function compactCurrency(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      notation: "compact",
      maximumFractionDigits: 1,
      signDisplay: "exceptZero"
    }).format(value);
  } catch {
    return `${currency} ${Math.round(value).toLocaleString("en-US")}`;
  }
}
