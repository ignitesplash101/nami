import { useRef, useState } from "react";
import type { RefObject } from "react";
import { BarChart3, Check, Copy, Pin, Save } from "lucide-react";
import {
  buildPositionValuations,
  buildWaterfallData,
  buildWaterfallDataDollars,
  factorReasoningRows,
  formatCurrency,
  formatPercent,
  formatSignedCurrency,
  parseNav,
  preferredAttributionMethod,
  selectMainAttribution,
  summarizeFactorTable,
  summarizeNameTable
} from "../charts";
import type { AttributionZoom } from "../charts";
import { csvFilename, downloadCsv } from "../csv";
import { factorDescription } from "../factors";
import { formatFxRate, formatMarkPrice, formatShares } from "../format";
import { AdjustmentPanel } from "../AdjustmentPanel";
import { CollapsibleCard } from "../CollapsibleCard";
import { EvidenceBlock } from "../EvidenceBlock";
import { FullscreenButton } from "../FullscreenButton";
import { TableScroll } from "../TableScroll";
import { Tabs } from "../Tabs";
import type { TabItem } from "../Tabs";
import { fullscreenChartHeight, useFullscreen, useViewportHeight } from "../useFullscreen";
import { useMediaQuery } from "../useMediaQuery";
import { RiskDiagnostics } from "./AttributionControl";
import { ExposureBreakdown } from "./ExposureBreakdown";
import { MethodologyDiagnostics } from "./MethodologyDiagnostics";
import { ExportCsvButton, SortableTh } from "./primitives";
import { ScenarioReadout } from "./ScenarioReadout";
import { WaterfallChart } from "./WaterfallChart";
import type {
  AttributionMethod,
  FactorMetadataMap,
  ScenarioResult,
  ScenarioRunResponse
} from "../types";

/** Results sub-tabs: the answer band (readout, evidence, toolbar, NAV metric)
 * always renders ABOVE these; the tabs split only the drill layer. */
export type ResultsTabKey = "drivers" | "positions" | "story" | "adjust" | "advanced";

export type ValuationSortKey =
  | "ticker"
  | "weight"
  | "shares"
  | "mark"
  | "value"
  | "stressed"
  | "delta"
  | "deltaPct";
export interface ValuationSort {
  key: ValuationSortKey;
  dir: "asc" | "desc";
}

export function ResultsPanel({
  envelope,
  factorMeta,
  displayMode,
  setDisplayMode,
  navInput,
  setNavInput,
  valuationSort,
  setValuationSort,
  isRunning = false,
  isStale = false,
  scrollRef,
  onOpenBook,
  resultsTab,
  onResultsTabChange,
  canAdjust = false,
  canonicalSnapshot = null,
  onAdjustResult,
  onPrefillRerun,
  onForbidden,
  canDecompose,
  isDecomposing,
  decomposeProgress,
  onDecompose,
  onCancelDecompose,
  onOpenMethodology,
  canSave,
  onSave,
  onPin,
  isPinned = false
}: {
  envelope: ScenarioRunResponse | null;
  factorMeta: FactorMetadataMap;
  displayMode: "pct" | "usd";
  setDisplayMode: (mode: "pct" | "usd") => void;
  navInput: string;
  setNavInput: (value: string) => void;
  valuationSort: ValuationSort;
  setValuationSort: (sort: ValuationSort) => void;
  isRunning?: boolean;
  // Prior results stay on screen, dimmed + aria-busy, while a re-run streams.
  isStale?: boolean;
  scrollRef?: RefObject<HTMLElement>;
  // Empty-state CTA into the "Your book" area (free pre-run analytics).
  onOpenBook?: () => void;
  // Sub-tab selection is App-owned so it persists across re-runs; when the
  // props are omitted (tests) an internal fallback state takes over.
  resultsTab?: ResultsTabKey;
  onResultsTabChange?: (tab: ResultsTabKey) => void;
  // Shock adjustment (admin): renders the "Adjust" sub-tab when permitted and
  // a canonical + cache_key exist (the server's provenance requirements).
  canAdjust?: boolean;
  canonicalSnapshot?: ScenarioResult | null;
  onAdjustResult?: (response: ScenarioRunResponse) => void;
  onPrefillRerun?: (text: string) => void;
  onForbidden?: () => void;
  canDecompose: boolean;
  isDecomposing: boolean;
  decomposeProgress: { done: number; total: number } | null;
  onDecompose: () => void;
  onCancelDecompose?: () => void;
  onOpenMethodology: (section?: string) => void;
  canSave: boolean;
  // Pin & compare: pins the CURRENT envelope for the App-level ComparisonPanel.
  onPin?: () => void;
  isPinned?: boolean;
  onSave: () => void;
}) {
  // Hooks live ABOVE the empty-state early return so the hook list is stable
  // across the null→result transition (the old in-App version relied on the
  // zero-hooks mount-dispatcher loophole; same rendered output, safer order).
  const isPhone = useMediaQuery("(max-width: 640px)");
  // Viewport-height bands: phone keeps the 320/-90°-ticks contract; short
  // laptops drop to 360; tall monitors get 480 instead of wasting space.
  const isShortViewport = useMediaQuery("(max-height: 720px)");
  const isTallViewport = useMediaQuery("(min-height: 900px)");
  const [reproCopied, setReproCopied] = useState(false);
  const [internalTab, setInternalTab] = useState<ResultsTabKey>("drivers");
  const activeTab = resultsTab ?? internalTab;
  const changeTab = onResultsTabChange ?? setInternalTab;
  // One methodology, two zooms (Phase 31i): the main waterfall always shows
  // the explicit conditional Shapley map (naive fallback for old payloads);
  // "group" rolls the SAME numbers up, so the zooms reconcile by construction.
  const [zoom, setZoom] = useState<AttributionZoom>("factor");
  const waterfallCardRef = useRef<HTMLDivElement>(null);
  const waterfallFullscreen = useFullscreen(waterfallCardRef, {
    surface: "contribution waterfall"
  });

  if (!envelope) {
    if (isRunning) {
      // First-run shimmer skeleton (reduced motion freezes it to a two-tone block).
      return (
        <section
          ref={scrollRef}
          className="empty-results results-skeleton"
          aria-label="Scenario results"
          aria-busy="true"
        >
          <span className="visually-hidden">Running scenario…</span>
          <div className="skeleton-block" style={{ height: 96 }} />
          <div className="skeleton-block" style={{ height: 48 }} />
          <div className="skeleton-block" style={{ height: 320 }} />
          <div className="skeleton-block" style={{ height: 180 }} />
        </section>
      );
    }
    return (
      <section ref={scrollRef} className="empty-results onboarding-empty" aria-label="Scenario results">
        <BarChart3 size={18} aria-hidden="true" />
        <div>
          <h3>No scenario run yet</h3>
          <p className="empty-invite">
            Describe a market shock in plain English above — or tap an example — and run it. nami
            models what it could do to this portfolio and shows the evidence behind every number.
          </p>
          {onOpenBook ? (
            <button type="button" className="ghost-button empty-book-cta" onClick={onOpenBook}>
              Or explore this book first — free factor profile &amp; event replay →
            </button>
          ) : null}
        </div>
      </section>
    );
  }
  const { result, analog_events } = envelope;
  const currency = result.reporting_currency ?? "USD";
  // Shares (MTM) results carry an authoritative marked NAV (read-only); otherwise
  // NAV is a client-side notional knob — instant what-if, no re-run.
  const isMarked = Boolean(result.position_quantities);
  const nav = isMarked ? result.portfolio_nav ?? null : parseNav(navInput);
  const hasNav = nav != null;
  const stressedNav = nav != null ? nav * (1 + result.portfolio_pnl.total_pnl) : null;
  const showDollars = hasNav && displayMode === "usd";
  const valuations = nav != null ? buildPositionValuations(result, nav) : [];
  const sortedValuations = [...valuations].sort((a, b) => {
    const { key, dir } = valuationSort;
    const sign = dir === "asc" ? 1 : -1;
    if (key === "ticker") return sign * a.ticker.localeCompare(b.ticker);
    const av = (a[key] as number | undefined) ?? 0;
    const bv = (b[key] as number | undefined) ?? 0;
    return sign * (av - bv);
  });
  const toggleSort = (key: ValuationSortKey) =>
    setValuationSort(
      valuationSort.key === key
        ? { key, dir: valuationSort.dir === "asc" ? "desc" : "asc" }
        : { key, dir: key === "ticker" ? "asc" : "desc" }
    );
  const sortHeader = (label: string, key: ValuationSortKey, numeric = true) => (
    <SortableTh
      label={label}
      active={valuationSort.key === key}
      dir={valuationSort.dir}
      onToggle={() => toggleSort(key)}
      numeric={numeric}
    />
  );
  const mainAttribution = selectMainAttribution(result);
  const waterfall =
    showDollars && nav != null
      ? buildWaterfallDataDollars(result, mainAttribution.method, nav, currency, factorMeta, zoom)
      : buildWaterfallData(result, mainAttribution.method, factorMeta, zoom);
  const factorRows = factorReasoningRows(result, mainAttribution.method, factorMeta);
  // Semantic export filenames: nami_<portfolio>_<scenario>_<as-of>_<table>.csv
  const exportName = (table: string) =>
    csvFilename(
      result.portfolio_key !== "custom" ? result.portfolio_key : result.portfolio_name,
      result.scenario_text,
      result.market_date,
      table
    );
  const exportFactorShocks = () =>
    downloadCsv(
      exportName("factor-shocks"),
      ["Factor", "Shock applied (decimal)", "Contribution to P&L (decimal)", "Reasoning"],
      factorRows.map((row) => [row.factorLabel, row.shockApplied, row.contribution, row.reasoning])
    );
  const exportNameLevel = () =>
    downloadCsv(
      exportName("name-level-contribution"),
      [
        "Ticker",
        "Weight (decimal)",
        "Factor (decimal)",
        "Periphery (decimal)",
        "Total (decimal)"
      ],
      Object.entries(result.portfolio_pnl.by_ticker_total)
        .sort((a, b) => a[1] - b[1])
        .map(([ticker, total]) => [
          ticker,
          result.portfolio_holdings[ticker] ?? 0,
          result.portfolio_pnl.by_ticker_factor[ticker] ?? 0,
          result.portfolio_pnl.by_ticker_periphery[ticker] ?? 0,
          total
        ])
    );
  const exportValuations = () =>
    downloadCsv(
      exportName("position-valuation"),
      [
        "Ticker",
        "Weight (decimal)",
        "Shares",
        "Mark",
        "Value (USD)",
        "Stressed (USD)",
        "Delta (USD)",
        "Delta (decimal)"
      ],
      // Respects the on-screen sort so the file matches what the user sees.
      sortedValuations.map((row) => [
        row.ticker,
        row.weight,
        row.shares ?? null,
        row.mark ?? null,
        row.value,
        row.stressed,
        row.delta,
        row.deltaPct
      ])
    );
  const exportAnalogs = () =>
    downloadCsv(
      exportName("analogs"),
      ["Event", "Start", "End", "Why relevant"],
      result.analogs_selected.map((analog) => {
        const event = analog_events[analog.event_id];
        return [
          event?.name ?? analog.event_id,
          event?.start_date ?? null,
          event?.end_date ?? null,
          analog.why_relevant
        ];
      })
    );
  const readoutMethod = preferredAttributionMethod(result);
  const peripheryTotal = Object.values(result.portfolio_pnl.by_ticker_periphery).reduce(
    (acc, value) => acc + value,
    0
  );
  const bandChartHeight = isPhone ? 320 : isShortViewport ? 360 : isTallViewport ? 480 : 420;
  const waterfallViewportHeight = useViewportHeight(waterfallFullscreen.isFullscreen);
  const chartHeight = fullscreenChartHeight(
    waterfallFullscreen.isFullscreen,
    bandChartHeight,
    waterfallViewportHeight
  );
  const reproducibility = envelope.reproducibility;

  async function copyReproducibility() {
    const repro = reproducibility;
    if (!repro) return;
    const text = `prompt ${repro.prompt_version} · model ${repro.model_id} · as-of ${repro.effective_as_of_date}`;
    try {
      await navigator.clipboard.writeText(text);
      setReproCopied(true);
      setTimeout(() => setReproCopied(false), 1500);
    } catch {
      // Clipboard unavailable (insecure origin) — no-op.
    }
  }

  // The Adjust tab needs the full provenance chain: permission + the trusted
  // canonical + a live cache_key (the server re-fetches the canonical by key).
  const showAdjust = Boolean(
    canAdjust && canonicalSnapshot && envelope.cache_key && onAdjustResult && onPrefillRerun
  );

  const resultsTabItems: TabItem<ResultsTabKey>[] = [
    {
      key: "drivers",
      label: "Drivers",
      content: (
        <>
          <div className="result-card waterfall-card fullscreen-surface" ref={waterfallCardRef}>
            <div className="card-heading">
              <div>
                <p className="eyebrow">Attribution</p>
                <h3>What drove the P&amp;L</h3>
                <p className="muted card-subtitle">
                  Systematic contribution waterfall — explicit conditional Shapley
                </p>
              </div>
              <div className="card-heading-actions">
                <div
                  className="segmented"
                  role="radiogroup"
                  aria-label="Attribution view"
                  onKeyDown={(event) => {
                    if (
                      event.key === "ArrowRight" ||
                      event.key === "ArrowDown" ||
                      event.key === "ArrowLeft" ||
                      event.key === "ArrowUp"
                    ) {
                      event.preventDefault();
                      setZoom(zoom === "factor" ? "group" : "factor");
                    }
                  }}
                >
                  <button
                    role="radio"
                    aria-checked={zoom === "factor"}
                    tabIndex={zoom === "factor" ? 0 : -1}
                    className={zoom === "factor" ? "active" : ""}
                    onClick={() => setZoom("factor")}
                    title="One bar per shocked factor"
                  >
                    By factor
                  </button>
                  <button
                    role="radio"
                    aria-checked={zoom === "group"}
                    tabIndex={zoom === "group" ? 0 : -1}
                    className={zoom === "group" ? "active" : ""}
                    onClick={() => setZoom("group")}
                    title="The same numbers rolled up into market / sector / style / macro"
                  >
                    By group
                  </button>
                </div>
                <FullscreenButton
                  controller={waterfallFullscreen}
                  surface="contribution waterfall"
                />
              </div>
            </div>
            {mainAttribution.degraded ? (
              <p className="muted">
                Conditional attribution unavailable for this result — showing the engine&apos;s
                naive algebra.
              </p>
            ) : null}
            <button
              type="button"
              className="guide-link"
              onClick={() => onOpenMethodology("factor-attribution")}
            >
              How the attribution works →
            </button>
            <RiskDiagnostics diagnostics={result.risk_diagnostics ?? []} factorMeta={factorMeta} />
            <WaterfallChart
              waterfall={waterfall}
              showDollars={showDollars}
              chartHeight={chartHeight}
              isPhone={isPhone}
            />
          </div>
          <CollapsibleCard
            className="table-card"
            title="Factor shocks and attribution"
            summary={summarizeFactorTable(result, factorMeta)}
            action={<ExportCsvButton label="Export factor shocks as CSV" onClick={exportFactorShocks} />}
          >
            <TableScroll>
            <table>
              <thead>
                <tr>
                  <th>Factor</th>
                  <th className="num">Shock</th>
                  <th className="num">P&L contrib</th>
                  <th>Reasoning</th>
                </tr>
              </thead>
              <tbody>
                {factorRows.map((row) => (
                  <tr key={row.factor} className={row.isCorrelationCredit ? "diagnostic-row" : ""}>
                    <td>
                      <button
                        className="factor-link"
                        onClick={() => onOpenMethodology("factor-universe")}
                        title={factorDescription(factorMeta, row.factor)}
                      >
                        {row.factorLabel}
                      </button>
                    </td>
                    <td className="num">{formatPercent(row.shockApplied)}</td>
                    <td className="num">{formatPercent(row.contribution)}</td>
                    <td>{row.reasoning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </TableScroll>
          </CollapsibleCard>
        </>
      )
    },
    {
      key: "positions",
      label: "Positions",
      content: (
        <>
          <ExposureBreakdown result={result} />
          <CollapsibleCard
            className="table-card"
            title="Name-level contribution"
            summary={summarizeNameTable(result)}
            action={
              <ExportCsvButton label="Export name-level contribution as CSV" onClick={exportNameLevel} />
            }
          >
            <TableScroll>
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th className="num">Weight</th>
                  <th className="num">Factor</th>
                  <th className="num">Periphery</th>
                  <th className="num">Total</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(result.portfolio_pnl.by_ticker_total)
                  .sort((a, b) => a[1] - b[1])
                  .map(([ticker, total]) => (
                    <tr key={ticker}>
                      <td>{ticker}</td>
                      <td className="num">{formatPercent(result.portfolio_holdings[ticker] ?? 0)}</td>
                      <td className="num">
                        {formatPercent(result.portfolio_pnl.by_ticker_factor[ticker] ?? 0)}
                      </td>
                      <td className="num">
                        {formatPercent(result.portfolio_pnl.by_ticker_periphery[ticker] ?? 0)}
                      </td>
                      <td className="num">{formatPercent(total)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
            </TableScroll>
          </CollapsibleCard>
          {hasNav ? (
            <CollapsibleCard
              eyebrow="Valuation"
              title="Position valuation — original → stressed"
              summary={
                stressedNav != null
                  ? `NAV ${formatCurrency(nav ?? 0, currency)} → ${formatCurrency(
                      stressedNav,
                      currency
                    )} stressed`
                  : undefined
              }
              action={
                <ExportCsvButton label="Export position valuation as CSV" onClick={exportValuations} />
              }
            >
              <TableScroll>
                <table className="valuation-table">
                  <thead>
                    <tr>
                      {sortHeader("Ticker", "ticker", false)}
                      {sortHeader("Weight", "weight")}
                      {isMarked ? sortHeader("Shares", "shares") : null}
                      {isMarked ? sortHeader("Mark", "mark") : null}
                      {sortHeader("Value", "value")}
                      {sortHeader("Stressed", "stressed")}
                      {sortHeader("Δ$", "delta")}
                      {sortHeader("Δ%", "deltaPct")}
                    </tr>
                  </thead>
                  <tbody>
                    {sortedValuations.map((row) => (
                      <tr key={row.ticker}>
                        <td>{row.ticker}</td>
                        <td className="num">{formatPercent(row.weight, 1)}</td>
                        {isMarked ? <td className="num">{formatShares(row.shares)}</td> : null}
                        {isMarked ? <td className="num">{formatMarkPrice(row.mark)}</td> : null}
                        <td className="num">{formatCurrency(row.value, currency)}</td>
                        <td className="num">{formatCurrency(row.stressed, currency)}</td>
                        <td className="num">{formatSignedCurrency(row.delta, currency)}</td>
                        <td className="num">{formatPercent(row.deltaPct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScroll>
              {isMarked && result.fx_rates && Object.keys(result.fx_rates).length > 1 ? (
                <p className="muted">
                  FX → USD:{" "}
                  {Object.entries(result.fx_rates)
                    .filter(([ccy]) => ccy !== "USD")
                    .map(
                      ([ccy, rate]) =>
                        `${formatFxRate(ccy, rate)} (${result.fx_date_by_currency?.[ccy] ?? "?"})`
                    )
                    .join(" · ")}
                </p>
              ) : (
                <p className="muted">
                  Notional dollar view — sample weights × the portfolio value (positions are not marked).
                </p>
              )}
            </CollapsibleCard>
          ) : null}
        </>
      )
    },
    {
      key: "story",
      label: "Story",
      content: (
        <CollapsibleCard
          className="narrative"
          eyebrow="Narrative"
          title="Narrative & analog evidence"
          summary={
            result.narrative.length > 90 ? `${result.narrative.slice(0, 89)}…` : result.narrative
          }
          action={
            <ExportCsvButton label="Export historical analogs as CSV" onClick={exportAnalogs} />
          }
        >
          <div className="two-column narrative-columns">
            <div className="narrative-inner">
              <h4>Grounded narrative</h4>
              <p>{result.narrative}</p>
              <div className="citation-list">
                {result.citations.map((citation) => (
                  <a key={citation.url} href={citation.url} target="_blank" rel="noreferrer">
                    {citation.title ?? citation.url}
                  </a>
                ))}
              </div>
            </div>
            <div className="analogs-inner">
              <h4>Historical analogs</h4>
              <TableScroll>
                <table>
                  <thead>
                    <tr>
                      <th>Event</th>
                      <th>Window</th>
                      <th>Why relevant</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.analogs_selected.map((analog) => {
                      const event = analog_events[analog.event_id];
                      return (
                        <tr key={analog.event_id}>
                          <td>{event?.name ?? analog.event_id}</td>
                          <td>{event ? `${event.start_date} -> ${event.end_date}` : "n/a"}</td>
                          <td>{analog.why_relevant}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </TableScroll>
            </div>
          </div>
        </CollapsibleCard>
      )
    },
    ...(showAdjust
      ? [
          {
            key: "adjust" as const,
            label: "Adjust",
            content: (
              <AdjustmentPanel
                envelope={envelope}
                canonicalSnapshot={canonicalSnapshot as ScenarioResult}
                factorMeta={factorMeta}
                onResult={onAdjustResult as (response: ScenarioRunResponse) => void}
                prefillRerun={onPrefillRerun as (text: string) => void}
                onForbidden={onForbidden}
              />
            )
          }
        ]
      : []),
    ...(canDecompose
      ? [
          {
            key: "advanced" as const,
            label: "Advanced",
            content: (
              <>
              <MethodologyDiagnostics result={result} factorMeta={factorMeta} />
              <CollapsibleCard
                eyebrow="Experimental"
                title="Which themes matter most"
                summary={
                  result.narrative_shapley
                    ? `${result.narrative_shapley.contributions.length} themes decomposed`
                    : "admin decomposition — pinned analogs, ~3–15 pipeline runs"
                }
                defaultOpen={Boolean(result.narrative_shapley) || isDecomposing}
                action={
                  <div className="button-row">
                    <button
                      className="ghost-button"
                      onClick={onDecompose}
                      disabled={!canDecompose || isDecomposing}
                    >
                      {isDecomposing
                        ? decomposeProgress
                          ? `Testing themes… ${decomposeProgress.done}/${decomposeProgress.total}`
                          : "Testing themes…"
                        : "Run theme sensitivity"}
                    </button>
                    {isDecomposing && onCancelDecompose ? (
                      <button className="ghost-button" onClick={onCancelDecompose}>
                        Cancel
                      </button>
                    ) : null}
                  </div>
                }
              >
                {result.narrative_shapley ? (
                  <TableScroll>
                    <table>
                      <thead>
                        <tr>
                          <th>#</th>
                          <th>Sub-narrative</th>
                          <th className="num">Shapley P&L</th>
                          {hasNav ? <th className="num">$</th> : null}
                          <th className="num">Relative</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.narrative_shapley.contributions.map((contribution) => (
                          <tr key={contribution.narrative_index}>
                            <td>{contribution.narrative_index + 1}</td>
                            <td>{contribution.narrative_text}</td>
                            <td className="num">{formatPercent(contribution.shapley_value)}</td>
                            {hasNav ? (
                              <td className="num">
                                {formatSignedCurrency(
                                  contribution.shapley_value * (nav ?? 0),
                                  currency
                                )}
                              </td>
                            ) : null}
                            <td className="num">{formatPercent(contribution.relative_contribution)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableScroll>
                ) : (
                  <p className="muted">
                    ~3–15 pipeline runs (~30–90s). The marginal shock each theme adds
                    <em> within the original analog context</em> (analogs pinned, no re-grounding) — a
                    theme-sensitivity view, illustrative, not causal. Current periphery total:{" "}
                    {formatPercent(peripheryTotal)}.
                  </p>
                )}
              </CollapsibleCard>
              </>
            )
          }
        ]
      : [])
  ];
  const safeTab: ResultsTabKey = resultsTabItems.some((item) => item.key === activeTab)
    ? activeTab
    : "drivers";

  return (
    <section
      ref={scrollRef}
      className={`results-stack${isStale ? " is-stale" : ""}`}
      aria-busy={isStale || undefined}
    >
      <div className="results-answer-band">
        <ScenarioReadout
          result={result}
          attributionMethod={readoutMethod}
          factorMeta={factorMeta}
          showDollars={showDollars}
          nav={nav}
          currency={currency}
        />
        <EvidenceBlock
          result={result}
          analogEvents={analog_events}
          showDollars={showDollars}
          nav={nav}
          currency={currency}
        />
      </div>
      <div className="results-toolbar">
        <div className="results-toolbar-left">
          {canSave ? (
            <button className="ghost-button" onClick={onSave}>
              <Save size={14} /> Save scenario
            </button>
          ) : null}
          {onPin ? (
            <button
              type="button"
              className="ghost-button"
              onClick={onPin}
              disabled={isPinned}
              title="Hold this result and compare the next run, adjustment, or opened scenario against it"
            >
              <Pin size={14} /> {isPinned ? "Pinned" : "Pin to compare"}
            </button>
          ) : null}
          {isMarked ? (
            <span className="muted nav-marked" title="Marked to the as-of close + FX">
              NAV <code>{formatCurrency(result.portfolio_nav ?? 0, currency)}</code> · marked
            </span>
          ) : (
            <label className="nav-knob">
              <span>Portfolio value</span>
              <input
                value={navInput}
                onChange={(event) => {
                  setNavInput(event.target.value);
                  if (parseNav(event.target.value) != null) setDisplayMode("usd");
                }}
                onFocus={(event) => event.currentTarget.select()}
                placeholder="e.g. $1,000,000"
                inputMode="decimal"
                aria-label="Portfolio value (USD) for the dollar view"
              />
            </label>
          )}
          {stressedNav != null ? (
            <span
              className={`nav-stressed ${result.portfolio_pnl.total_pnl >= 0 ? "up" : "down"}`}
            >
              → {formatCurrency(stressedNav, currency)} stressed
            </span>
          ) : null}
          {hasNav ? (
            <div className="segmented results-units" role="radiogroup" aria-label="P&L units">
              <button
                role="radio"
                aria-checked={!showDollars}
                className={!showDollars ? "active" : ""}
                onClick={() => setDisplayMode("pct")}
                title="Show P&L as percentages"
              >
                %
              </button>
              <button
                role="radio"
                aria-checked={showDollars}
                className={showDollars ? "active" : ""}
                onClick={() => setDisplayMode("usd")}
                title="Show P&L in dollars"
              >
                $
              </button>
            </div>
          ) : null}
        </div>
        {envelope.reproducibility ? (
          <span className="muted reproducibility-chip">
            prompt {envelope.reproducibility.prompt_version} · model{" "}
            {envelope.reproducibility.model_id} · as-of{" "}
            <code>{envelope.reproducibility.effective_as_of_date}</code>
            <button
              type="button"
              className="chip-copy-btn"
              aria-label="Copy reproducibility details"
              title="Copy reproducibility details"
              onClick={copyReproducibility}
            >
              {reproCopied ? <Check size={12} /> : <Copy size={12} />}
            </button>
          </span>
        ) : null}
      </div>
      <Tabs
        className="results-tabs"
        idBase="results"
        ariaLabel="Result detail views"
        items={resultsTabItems}
        active={safeTab}
        onChange={changeTab}
      />
    </section>
  );
}
