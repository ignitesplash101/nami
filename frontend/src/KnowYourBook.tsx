import { Download } from "lucide-react";
import { useRef, useState } from "react";
import { buildBookProfileRows, formatPercent } from "./charts";
import { ChoiceGroup } from "./ChoiceGroup";
import { GLOSSARY } from "./copy/glossary";
import { InfoTip } from "./copy/InfoTip";
import { csvFilename, downloadCsv } from "./csv";
import { factorDisplayName } from "./factors";
import { FullscreenButton } from "./FullscreenButton";
import { TableScroll } from "./TableScroll";
import type { BookProfile, EventsReplay, FactorMetadataMap } from "./types";
import { useFullscreen } from "./useFullscreen";

/** The pre-run "know this book" card: the free engine-only analytics (book
 *  profile, all-events replay) behind one segmented control instead of two
 *  stacked CTAs + cards. Each tab lazy-fetches on first activation; results
 *  clear on book changes upstream exactly as before. */
export function KnowYourBook({
  bookName,
  bookDescription,
  benchmark,
  profile,
  replay,
  profileBusy,
  replayBusy,
  onProfile,
  onReplay,
  unavailableReason,
  factorMeta
}: {
  bookName?: string;
  bookDescription?: string;
  benchmark?: string | null;
  profile: BookProfile | null;
  replay: EventsReplay | null;
  profileBusy: boolean;
  replayBusy: boolean;
  onProfile: () => void;
  onReplay: () => void;
  unavailableReason: string | null;
  factorMeta: FactorMetadataMap;
}) {
  const [tab, setTab] = useState<"profile" | "events">("profile");
  const busy = tab === "profile" ? profileBusy : replayBusy;
  const hasData = tab === "profile" ? profile != null : replay != null;
  const fetchActive = tab === "profile" ? onProfile : onReplay;
  const ctaLabel = tab === "profile" ? "Profile this book" : "Replay every historical event";
  const ref = useRef<HTMLElement>(null);
  const fs = useFullscreen(ref, { surface: "book analytics" });

  return (
    <section className="result-card know-book fullscreen-surface" ref={ref} aria-label="Understand this book">
      {bookName ? (
        <div className="book-context">
          <div className="book-context-identity">
            <span className="eyebrow">Current book</span>
            <strong>{bookName}</strong>
          </div>
          {bookDescription ? (
            <p className="muted book-context-description">{bookDescription}</p>
          ) : null}
          {benchmark ? (
            <p className="muted book-context-benchmark">
              Benchmark: <code>{benchmark}</code>
            </p>
          ) : null}
        </div>
      ) : null}
      <div className="card-heading">
        <div>
          <p className="eyebrow">Free, no LLM</p>
          <h3>Pre-run analytics</h3>
          <p className="muted card-subtitle">Pure engine math, no LLM call.</p>
        </div>
        <div className="card-heading-actions">
          <ChoiceGroup
            ariaLabel="Pre-run analytic"
            className="segmented"
            value={tab}
            onChange={setTab}
            options={[
              { key: "profile", label: "Book profile" },
              { key: "events", label: "Event replay" }
            ]}
          />
          <FullscreenButton controller={fs} surface="book analytics" />
        </div>
      </div>

      {!hasData ? (
        <div className="know-book-cta">
          <button
            type="button"
            className="ghost-button"
            onClick={fetchActive}
            disabled={busy || Boolean(unavailableReason)}
          >
            {busy && tab === "events" ? "Loading historical events…" : busy ? "Computing…" : ctaLabel}
          </button>
          {unavailableReason ? <span className="field-note">{unavailableReason}</span> : null}
          {tab === "events" && replayBusy ? (
            <span className="field-note">
              The first load can take a couple of minutes. Later replays reuse the shared cache.
            </span>
          ) : null}
        </div>
      ) : null}

      {tab === "profile" && profile ? <ProfileBody profile={profile} factorMeta={factorMeta} /> : null}
      {tab === "events" && replay ? <EventsBody replay={replay} /> : null}
    </section>
  );
}

function ProfileBody({
  profile,
  factorMeta
}: {
  profile: BookProfile;
  factorMeta: FactorMetadataMap;
}) {
  const rows = buildBookProfileRows(
    profile.factor_exposures,
    (key) => factorDisplayName(factorMeta, key),
    10
  );
  const maxAbs = Math.max(...rows.map((row) => Math.abs(row.exposure)), 1e-9);
  return (
    <div className="know-book-body book-profile-layout" aria-label="Book profile">
      <div className="book-profile-summary">
        <p className="muted book-profile-asof">
          {profile.portfolio_name} · as of {profile.as_of} · {profile.n_factors} factors
        </p>
        <div className="exposure-bars" role="list" aria-label="Portfolio factor exposures">
          {rows.map((row) => (
            <div key={row.key} className="exposure-bar-row" role="listitem">
              <span className="exposure-bar-label">{row.label}</span>
              <span className="exposure-bar-track" aria-hidden="true">
                <span
                  className={`exposure-bar-fill ${row.exposure < 0 ? "neg" : "pos"}`}
                  style={{ width: `${(Math.abs(row.exposure) / maxAbs) * 100}%` }}
                />
              </span>
              <span className="exposure-bar-value">{row.exposure.toFixed(2)}</span>
            </div>
          ))}
        </div>
        <p className="hint">
          How hard a 1% move in each factor would hit this book (top {rows.length} of{" "}
          {profile.n_factors} by size)
          <InfoTip label="About portfolio beta">
            {GLOSSARY.portfolioBeta.detail} Shown ±{formatPercent(profile.idio_band_weekly)} weekly
            idio — a dispersion floor, not a confidence interval.
          </InfoTip>
        </p>
      </div>
      <div className="book-profile-diagnostics">
        <TableScroll>
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th className="num">Weight</th>
                <th className="num">
                  R² adj
                  <InfoTip label="About adjusted R-squared">{GLOSSARY.rSquaredAdj.plain}</InfoTip>
                </th>
                <th className="num">Weeks</th>
                <th className="num">
                  Idio vol (wk)
                  <InfoTip label="About idiosyncratic volatility">
                    {GLOSSARY.idioVolWeekly.plain}
                  </InfoTip>
                </th>
              </tr>
            </thead>
            <tbody>
              {profile.per_name.map((row) => (
                <tr key={row.ticker}>
                  <td>{row.ticker}</td>
                  <td className="num">{formatPercent(row.weight, 1)}</td>
                  <td className="num">{row.r2_adj != null ? row.r2_adj.toFixed(2) : "—"}</td>
                  <td className="num">{row.n_obs ?? "—"}</td>
                  <td className="num">
                    {row.idio_vol_weekly != null ? formatPercent(row.idio_vol_weekly) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      </div>
    </div>
  );
}

function EventsBody({ replay }: { replay: EventsReplay }) {
  const exportCsv = () =>
    downloadCsv(
      csvFilename(replay.portfolio_name, "all-events", replay.as_of, "events-replay"),
      ["event", "start", "end", "days", "modeled_pnl", "factors_covered", "tags"],
      replay.per_event.map((row) => [
        row.name,
        row.start_date,
        row.end_date,
        row.window_calendar_days,
        row.replay_pnl,
        row.n_factors_covered,
        row.tags.join("|")
      ])
    );
  return (
    <div className="know-book-body events-replay" aria-label="Historical event replay">
      <div className="know-book-subhead">
        <p className="muted book-profile-asof">
          {replay.per_event.length} historical events × {replay.portfolio_name} · as of{" "}
          {replay.as_of}, worst first
        </p>
        <button
          type="button"
          className="ghost-button table-export-btn"
          onClick={exportCsv}
          aria-label="Export event replay as CSV"
          title="Export event replay as CSV"
        >
          <Download size={13} /> CSV
        </button>
      </div>
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Event</th>
              <th>Window</th>
              <th className="num">Days</th>
              <th className="num">Modeled P&L</th>
              <th className="num">Coverage</th>
            </tr>
          </thead>
          <tbody>
            {replay.per_event.map((row) => (
              <tr key={row.event_id}>
                <td>{row.name}</td>
                <td className="events-replay-window">
                  {row.start_date} → {row.end_date}
                </td>
                <td className="num">{row.window_calendar_days}</td>
                <td className={`num ${row.replay_pnl < 0 ? "loss" : "gain"}`}>
                  {formatPercent(row.replay_pnl)}
                </td>
                <td className="num">
                  {row.n_factors_covered}/{replay.n_factors}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
      <p className="hint">
        Each event's realized factor moves pushed through this book's current betas. Factor-model
        only — no idiosyncratic or periphery effects, current betas on historical windows. A
        severity screen, not a backtest and not a forecast.
      </p>
    </div>
  );
}
