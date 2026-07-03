import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import Plot from "react-plotly.js";
import {
  Activity,
  ArrowRight,
  BarChart3,
  BookOpen,
  Check,
  Command,
  Copy,
  Download,
  Lock,
  LogOut,
  Menu,
  Save,
  Shield,
  Table2,
  Unlock,
  Upload
} from "lucide-react";
import {
  ApiError,
  decomposeScenarioStream,
  getAccess,
  getFactors,
  getMethodology,
  getSamplePortfolios,
  getSampleScenarios,
  getTickerMetadata,
  lock,
  profileBook,
  purgeAllData,
  runScenarioStream,
  toApiError,
  unlock,
  validatePortfolio
} from "./api";
import { ConfirmDialog } from "./ConfirmDialog";
import { ErrorNotice } from "./ErrorNotice";
import { OpsDrawer } from "./OpsDrawer";
import { scrollBehavior } from "./motion";
import { createRunLifecycle } from "./runLifecycle";
import { useToasts } from "./toast";
import { nextSessionExpired, useAccessWatch } from "./useAccessWatch";
import {
  buildAnalogReplayRows,
  buildPositionValuations,
  buildBookProfileRows,
  buildReadout,
  buildWaterfallData,
  buildWaterfallDataDollars,
  chartTheme,
  factorReasoningRows,
  formatCurrency,
  formatPercent,
  formatSignedCurrency,
  groupByTag,
  normalizeTicker,
  parseNav,
  preferredAttributionMethod,
} from "./charts";
import { csvFilename, downloadCsv } from "./csv";
import { factorDescription, factorDisplayName, factorMap } from "./factors";
import { formatEvidence, formatFxRate, formatMarkPrice, formatShares } from "./format";
import { TableScroll } from "./TableScroll";
import { AdjustmentPanel } from "./AdjustmentPanel";
import { AsOfDatePicker, BackdatedModeBanner } from "./AsOfDatePicker";
import { CommandPalette } from "./CommandPalette";
import type { CommandAction } from "./CommandPalette";
import { AttributionGuide } from "./AttributionGuide";
import { nextEnabledMethod } from "./attributionNav";
import { getSavedScenario } from "./api";
import { MethodologyDrawer } from "./MethodologyDrawer";
import { PortfolioHistoryPanel } from "./PortfolioHistoryPanel";
import { RailDrawer } from "./RailDrawer";
import { RunProgress } from "./RunProgress";
import { SaveScenarioDialog } from "./SaveScenarioDialog";
import { SavedScenariosPanel } from "./SavedScenariosPanel";
import { useMediaQuery } from "./useMediaQuery";
import { useMethodologyDrawer } from "./useMethodologyDrawer";
import { useOverlay } from "./useOverlay";
import type {
  AccessResponse,
  AnalogEvent,
  AttributionMethod,
  BookProfile,
  FactorMetadataMap,
  PortfolioSnapshotRecord,
  RiskDiagnostic as RiskDiagnosticRecord,
  SamplePortfolio,
  SampleScenario,
  ScenarioResult,
  ScenarioRunResponse,
  SsePipelineStage,
  TickerMetadata
} from "./types";

type WaterfallTrace = {
  type: "waterfall";
  orientation: "v";
  x: string[];
  y: number[];
  measure: ("relative" | "total")[];
  text: string[];
  hovertext: string[];
  hovertemplate: string;
  textposition: "outside";
  connector: { line: { color: string } };
  increasing: { marker: { color: string } };
  decreasing: { marker: { color: string } };
  totals: { marker: { color: string } };
};

interface HoldingRow {
  id: string;
  ticker: string;
  weight: string;
}

type PortfolioMode = "sample" | "custom";
type ScenarioDraftMode = "sample" | "custom";

type ValuationSortKey =
  | "ticker"
  | "weight"
  | "shares"
  | "mark"
  | "value"
  | "stressed"
  | "delta"
  | "deltaPct";
interface ValuationSort {
  key: ValuationSortKey;
  dir: "asc" | "desc";
}

const defaultCustomRows: HoldingRow[] = [
  { id: "row-aapl", ticker: "AAPL", weight: "0.5" },
  { id: "row-msft", ticker: "MSFT", weight: "0.5" }
];

function holdingsFromRows(rows: HoldingRow[]): Record<string, number> {
  const holdings: Record<string, number> = {};
  for (const row of rows) {
    const ticker = normalizeTicker(row.ticker);
    if (!ticker) continue;
    holdings[ticker] = Number(row.weight);
  }
  return holdings;
}

function parseCsv(text: string): HoldingRow[] {
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

export default function App() {
  const [access, setAccess] = useState<AccessResponse | null>(null);
  const [portfolios, setPortfolios] = useState<SamplePortfolio[]>([]);
  const [scenarios, setScenarios] = useState<SampleScenario[]>([]);
  const [factorMeta, setFactorMeta] = useState<FactorMetadataMap>({});
  const [portfolioKey, setPortfolioKey] = useState("us_tech_growth");
  const [scenarioKey, setScenarioKey] = useState("china_tariffs");
  const [scenarioDraftMode, setScenarioDraftMode] = useState<ScenarioDraftMode>("sample");
  const [portfolioMode, setPortfolioMode] = useState<PortfolioMode>("sample");
  const [customName, setCustomName] = useState("Custom Book");
  const [customRows, setCustomRows] = useState<HoldingRow[]>(defaultCustomRows);
  // MTM: "weights" = today's weight model (+ optional NAV scalar); "shares" = true
  // mark-to-market (server marks the share counts to the as-of close, FX→USD).
  const [customUnits, setCustomUnits] = useState<"weights" | "shares">("weights");
  // Optional benchmark ticker for a custom book (sample books carry their own).
  const [customBenchmark, setCustomBenchmark] = useState("");
  // Free pre-scenario book profile (zero LLM). Cleared whenever the book
  // selection changes so a stale profile can't describe a different portfolio.
  const [bookProfile, setBookProfile] = useState<BookProfile | null>(null);
  const [profileBusy, setProfileBusy] = useState(false);
  // Default every book to a $100k notional value so the dollar view (P&L,
  // stressed values, position table) is populated out-of-the-box for everyone,
  // incl. visitors. Pure client-side notional scaling — NOT mark-to-market.
  const [navInput, setNavInput] = useState("100000");
  // Results display: percent (default) vs dollars (enabled once a NAV exists).
  const [displayMode, setDisplayMode] = useState<"pct" | "usd">("pct");
  // Position-valuation sort: click a column header to sort, click again to flip.
  // Default = biggest losses first (the decision-relevant view for a shock).
  const [valuationSort, setValuationSort] = useState<ValuationSort>({ key: "delta", dir: "asc" });
  const [scenarioText, setScenarioText] = useState("");
  // As-of date (YYYY-MM-DD). Seeded from access.latest_market_date on boot;
  // equal-to-latest-close means live, earlier means backdated.
  const [asOfDate, setAsOfDate] = useState<string>("");
  const [resultEnvelope, setResultEnvelope] = useState<ScenarioRunResponse | null>(null);
  const [canonicalSnapshot, setCanonicalSnapshot] = useState<ScenarioResult | null>(null);
  const [savedReloadKey, setSavedReloadKey] = useState(0);
  const saveDialog = useOverlay();
  const [methodology, setMethodology] = useState("");
  const [attributionMethod, setAttributionMethod] = useState<AttributionMethod>("naive");
  const [isRunning, setIsRunning] = useState(false);
  const [isDecomposing, setIsDecomposing] = useState(false);
  const [decomposeProgress, setDecomposeProgress] = useState<{ done: number; total: number } | null>(
    null
  );
  const [error, setError] = useState<ApiError | string | null>(null);
  const [currentStage, setCurrentStage] = useState<SsePipelineStage | null>(null);
  const [stageStatus, setStageStatus] = useState<"start" | "done" | null>(null);
  const [completedStages, setCompletedStages] = useState<Set<SsePipelineStage>>(new Set());
  const [cacheHit, setCacheHit] = useState(false);
  // True only when an admin session silently downgraded (cookie expiry) — a
  // deliberate lock passes intentional=true through applyAccess and stays quiet.
  const [sessionExpired, setSessionExpired] = useState(false);
  const [bootSerial, setBootSerial] = useState(0);
  const accessModeRef = useRef<AccessResponse["access_mode"] | null>(null);
  const lastFailedActionRef = useRef<"run" | "decompose" | "boot" | null>(null);
  const passcodeInputRef = useRef<HTMLInputElement>(null);
  // Separate lifecycles: cancelling/superseding a run must not abort an
  // in-flight decomposition and vice versa.
  const runLifecycle = useRef(createRunLifecycle()).current;
  const decomposeLifecycle = useRef(createRunLifecycle()).current;
  // Bumped only when a RUN completes (not adjustments or saved-scenario opens):
  // the effect below scrolls the fresh results into view.
  const [runSerial, setRunSerial] = useState(0);
  const resultsRef = useRef<HTMLElement>(null);
  const { push: pushToast } = useToasts();
  const methodologyDrawer = useMethodologyDrawer();
  const railDrawer = useOverlay();
  const commandPalette = useOverlay();
  const opsDrawer = useOverlay();
  const purgeConfirm = useOverlay();
  const [purgeBusy, setPurgeBusy] = useState(false);
  // Bumped on purge success and passed as `key` to the saved-scenarios +
  // portfolio-history panels: the backend purge deletes portfolios/snapshots
  // too, and those panels fetch on mount/selection only — a remount resets
  // their local state instead of leaving deleted records on screen.
  const [adminDataEpoch, setAdminDataEpoch] = useState(0);
  const isMobileOrTablet = useMediaQuery("(max-width: 1079.98px)");

  function openMethodology(section?: string) {
    railDrawer.close();
    commandPalette.close();
    opsDrawer.close();
    methodologyDrawer.open(section);
  }

  function openRailDrawer() {
    methodologyDrawer.close();
    commandPalette.close();
    opsDrawer.close();
    railDrawer.open();
  }

  function openOpsDrawer() {
    methodologyDrawer.close();
    railDrawer.close();
    commandPalette.close();
    opsDrawer.open();
  }

  // Purge flow: the ops drawer CLOSES before the confirm dialog opens — two
  // useOverlay overlays must never be open at once (window-level Esc would
  // close both together).
  function requestPurge() {
    opsDrawer.close();
    purgeConfirm.open();
  }

  async function handlePurgeConfirmed() {
    setPurgeBusy(true);
    try {
      const counts = await purgeAllData("DELETE");
      pushToast({
        variant: "success",
        message: `Purged ${counts.scenarios} scenarios, ${counts.portfolios} portfolios, ${counts.snapshots} snapshots.`
      });
      setAdminDataEpoch((epoch) => epoch + 1);
      purgeConfirm.close();
    } catch (exc) {
      purgeConfirm.close();
      reportError(exc);
    } finally {
      setPurgeBusy(false);
    }
  }

  // ⌘K / Ctrl+K opens the command palette (accelerator only — every command it
  // exposes also has a visible control elsewhere). open/close are stable.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        methodologyDrawer.close();
        railDrawer.close();
        opsDrawer.close();
        commandPalette.open();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [commandPalette.open, methodologyDrawer.close, opsDrawer.close, railDrawer.close]);

  useEffect(() => {
    async function boot() {
      const [accessResponse, portfolioResponse, scenarioResponse, factorResponse, methodologyText] =
        await Promise.all([
          getAccess(),
          getSamplePortfolios(),
          getSampleScenarios(),
          getFactors().catch(() => []),
          getMethodology().catch(() => "")
        ]);
      applyAccess(accessResponse);
      // Seed the as-of picker with the latest NYSE close (the live anchor), so
      // "live" means the latest US close rather than the browser's local day.
      setAsOfDate(accessResponse.latest_market_date);
      setPortfolios(portfolioResponse);
      setScenarios(scenarioResponse);
      setFactorMeta(factorMap(factorResponse));
      setPortfolioKey(portfolioResponse[0]?.key ?? "us_tech_growth");
      setScenarioKey(scenarioResponse[0]?.key ?? "china_tariffs");
      setScenarioText(scenarioResponse[0]?.text ?? "");
      setScenarioDraftMode("sample");
      setMethodology(methodologyText);

      // Permalink hydration: ?saved=<id> opens a saved scenario directly.
      // Admin-only (matches the underlying endpoint gating).
      const params = new URLSearchParams(window.location.search);
      const savedId = params.get("saved");
      if (savedId && accessResponse.access_mode === "admin") {
        try {
          const rec = await getSavedScenario(savedId);
          setResultEnvelope({
            result: rec.result,
            analog_events: rec.analog_events_snapshot,
            cache_key: null,
            reproducibility: rec.reproducibility
          });
          setCanonicalSnapshot(rec.result);
          setAttributionMethod(preferredAttributionMethod(rec.result));
        } catch (exc) {
          setError(`Could not load saved scenario: ${exc instanceof Error ? exc.message : exc}`);
        }
      }
    }
    boot().catch((exc: unknown) => reportError(exc, "boot"));
    // bootSerial lets the error banner's Retry re-run a failed boot.
  }, [bootSerial]);

  useEffect(() => {
    const selected = scenarios.find((scenario) => scenario.key === scenarioKey);
    if (selected && scenarioDraftMode === "sample") {
      setScenarioText(selected.text);
    }
  }, [scenarioDraftMode, scenarioKey, scenarios]);

  // Post-commit scroll so the freshly landed results DOM exists; gated through
  // scrollBehavior() per the reduced-motion contract.
  useEffect(() => {
    if (runSerial === 0) return;
    resultsRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
  }, [runSerial]);

  const selectedPortfolio = useMemo(
    () => portfolios.find((portfolio) => portfolio.key === portfolioKey) ?? portfolios[0],
    [portfolioKey, portfolios]
  );
  const selectedScenario = useMemo(
    () => scenarios.find((scenario) => scenario.key === scenarioKey) ?? scenarios[0],
    [scenarioKey, scenarios]
  );

  const isAdmin = access?.access_mode === "admin";

  // Every access update routes through here so a silent admin→visitor
  // downgrade (cookie expiry) raises the session banner exactly once.
  function applyAccess(next: AccessResponse, opts?: { intentional?: boolean }) {
    const prev = accessModeRef.current;
    accessModeRef.current = next.access_mode;
    if (next.access_mode === "admin") {
      setSessionExpired(false);
    } else if (nextSessionExpired(prev, next.access_mode, Boolean(opts?.intentional))) {
      setSessionExpired(true);
    }
    setAccess(next);
  }

  async function refreshAccess() {
    applyAccess(await getAccess());
  }

  useAccessWatch({ enabled: access != null, onAccess: applyAccess });

  // Normalize any failure into an ApiError; cancelled runs stay silent and a
  // forbidden response triggers an access re-check (catches stale admin cookies).
  // A profile describes exactly one book — drop it whenever the selection or
  // the custom holdings change so a stale profile can't describe another book.
  useEffect(() => {
    setBookProfile(null);
  }, [portfolioKey, portfolioMode, customRows, customUnits]);

  async function handleProfileBook() {
    setProfileBusy(true);
    setError(null);
    try {
      const payload =
        portfolioMode === "sample"
          ? { portfolio_key: portfolioKey }
          : {
              portfolio_holdings: holdingsFromRows(customRows),
              portfolio_name: customName || undefined
            };
      setBookProfile(await profileBook(payload));
    } catch (exc) {
      reportError(exc);
    } finally {
      setProfileBusy(false);
    }
  }

  function reportError(exc: unknown, action: "run" | "decompose" | "boot" | null = null) {
    const err = toApiError(exc);
    if (err.kind === "cancelled") return;
    if (err.kind === "forbidden") void refreshAccess().catch(() => {});
    lastFailedActionRef.current = action;
    setError(err);
  }

  function retryLastAction() {
    const action = lastFailedActionRef.current;
    setError(null);
    if (action === "run") void handleRun();
    else if (action === "decompose") void handleDecompose();
    else if (action === "boot") setBootSerial((serial) => serial + 1);
  }

  function focusUnlock() {
    if (isMobileOrTablet) {
      openRailDrawer();
      requestAnimationFrame(() => passcodeInputRef.current?.focus());
    } else {
      passcodeInputRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: "center" });
      passcodeInputRef.current?.focus();
    }
  }

  function handleScenarioSeed(key: string) {
    const scenario = scenarios.find((item) => item.key === key);
    setScenarioKey(key);
    setScenarioDraftMode("sample");
    if (scenario) setScenarioText(scenario.text);
  }

  function handleScenarioTextChange(text: string) {
    setScenarioText(text);
    setScenarioDraftMode(text.trim() === selectedScenario?.text.trim() ? "sample" : "custom");
  }

  async function handleRun() {
    if (!access) return;
    // begin() aborts any in-flight run and invalidates its sequence — its late
    // frames/result/finally are dropped by the isCurrent guards below.
    const handle = runLifecycle.begin();
    setError(null);
    setIsRunning(true);
    setCurrentStage(null);
    setStageStatus(null);
    setCompletedStages(new Set());
    setCacheHit(false);
    try {
      const sharesMode = portfolioMode === "custom" && customUnits === "shares";
      const baseAdmin = {
        scenario_text: scenarioText || selectedScenario?.text,
        portfolio_key: portfolioMode === "sample" ? portfolioKey : undefined,
        portfolio_name: portfolioMode === "custom" ? customName : undefined,
        portfolio_holdings:
          portfolioMode === "custom" && !sharesMode ? holdingsFromRows(customRows) : undefined,
        // Mark-to-market: admin share quantities marked to the as-of close + FX.
        // (Notional dollar scaling is a client-side post-run control, not a run input.)
        position_quantities: sharesMode ? holdingsFromRows(customRows) : undefined,
        reporting_currency: sharesMode ? "USD" : undefined,
        // Custom books pass an explicit benchmark; sample books fall back to their
        // own assigned benchmark server-side (so leave it undefined there).
        benchmark:
          portfolioMode === "custom" && customBenchmark.trim()
            ? customBenchmark.trim()
            : undefined,
        // Only thread as_of_date when admin chose a date EARLIER than the latest
        // close. The latest close (the default) means "live" — send undefined so
        // the backend takes the grounded (Google Search) path.
        as_of_date:
          asOfDate && asOfDate !== access.latest_market_date ? asOfDate : undefined
      };
      const payload = isAdmin
        ? baseAdmin
        : scenarioDraftMode === "custom"
          ? {
              scenario_text: scenarioText.trim(),
              portfolio_key: portfolioKey
            }
          : {
              sample_scenario_key: scenarioKey,
              portfolio_key: portfolioKey
            };
      const response = await runScenarioStream(
        payload,
        (event) => {
          if (!runLifecycle.isCurrent(handle.seq)) return;
          if (event.stage === "cache_hit") {
            setCacheHit(true);
            return;
          }
          if (event.stage === "done" || event.stage === "error") {
            return;
          }
          setCurrentStage(event.stage);
          setStageStatus(event.status ?? null);
          if (event.status === "done") {
            setCompletedStages((prev) => new Set(prev).add(event.stage));
          }
        },
        { signal: handle.signal }
      );
      if (!runLifecycle.isCurrent(handle.seq)) return;
      setResultEnvelope(response);
      setCanonicalSnapshot(response.result);
      setAttributionMethod(preferredAttributionMethod(response.result));
      setRunSerial((serial) => serial + 1);
      // Surface dollars by default when the run is marked (shares) OR a notional
      // portfolio value is already entered (sticky knob); otherwise stay in percent.
      setDisplayMode(
        response.result.portfolio_nav != null || parseNav(navInput) != null ? "usd" : "pct"
      );
    } catch (exc) {
      if (!runLifecycle.isCurrent(handle.seq)) return;
      reportError(exc, "run");
    } finally {
      if (runLifecycle.isCurrent(handle.seq)) {
        setIsRunning(false);
      }
    }
  }

  function handleCancelRun() {
    runLifecycle.cancel();
  }

  function handleAdjustmentResult(response: ScenarioRunResponse) {
    setResultEnvelope(response);
  }

  function handlePrefillRerun(text: string) {
    setScenarioText(text);
    setScenarioDraftMode("custom");
  }

  async function handleDecompose() {
    if (!resultEnvelope) return;
    const handle = decomposeLifecycle.begin();
    setError(null);
    setIsDecomposing(true);
    setDecomposeProgress(null);
    try {
      const response = await decomposeScenarioStream(
        resultEnvelope.result,
        (done, total) => {
          if (decomposeLifecycle.isCurrent(handle.seq)) setDecomposeProgress({ done, total });
        },
        { signal: handle.signal }
      );
      if (!decomposeLifecycle.isCurrent(handle.seq)) return;
      setResultEnvelope(response);
    } catch (exc) {
      if (!decomposeLifecycle.isCurrent(handle.seq)) return;
      reportError(exc, "decompose");
    } finally {
      if (decomposeLifecycle.isCurrent(handle.seq)) {
        setIsDecomposing(false);
        setDecomposeProgress(null);
      }
    }
  }

  function handleCancelDecompose() {
    decomposeLifecycle.cancel();
  }

  // Palette actions are a thin accelerator over already-visible controls. Built
  // fresh each render so the closures read current state (cheap; small list).
  const commandActions: CommandAction[] = [
    { id: "run", label: "Run scenario", hint: "Enter", run: () => void handleRun() },
    { id: "setup", label: "Open portfolio & access setup", run: openRailDrawer },
    { id: "methodology", label: "Open methodology", run: () => openMethodology() }
  ];
  if (resultEnvelope) {
    commandActions.push({
      id: "toggle-units",
      label: "Toggle dollars / percent view",
      run: () => setDisplayMode(displayMode === "usd" ? "pct" : "usd")
    });
  }
  if (isAdmin && resultEnvelope?.reproducibility) {
    commandActions.push({ id: "save", label: "Save scenario", run: saveDialog.open });
  }
  if (isAdmin && resultEnvelope) {
    commandActions.push({
      id: "decompose",
      label: "Run theme sensitivity",
      run: () => void handleDecompose()
    });
  }
  if (isAdmin) {
    commandActions.push({
      id: "ops",
      label: "Open operations console",
      run: openOpsDrawer
    });
    commandActions.push({
      id: "lock",
      label: "Lock (return to visitor mode)",
      run: () => {
        void lock().then((response) => applyAccess(response, { intentional: true }));
      }
    });
  }

  const railContent = (
    <>
      <div className="brand-block">
        <span className="brand-glyph" aria-hidden="true">波</span>
        <div className="brand-kicker">nami</div>
        <h1>Scenario Explorer</h1>
        <p>Equity portfolio shocks, analog-grounded narratives, factor attribution.</p>
        <div className="brand-crest" aria-hidden="true" />
      </div>
      <AccessPanel access={access} onAccessChange={applyAccess} passcodeInputRef={passcodeInputRef} />
      <PortfolioPanel
        access={access}
        portfolios={portfolios}
        portfolioKey={portfolioKey}
        setPortfolioKey={setPortfolioKey}
        portfolioMode={portfolioMode}
        setPortfolioMode={setPortfolioMode}
        customName={customName}
        setCustomName={setCustomName}
        customRows={customRows}
        setCustomRows={setCustomRows}
        customUnits={customUnits}
        setCustomUnits={setCustomUnits}
        customBenchmark={customBenchmark}
        setCustomBenchmark={setCustomBenchmark}
      />
    </>
  );

  return (
    <main className="app-shell">
      {!isMobileOrTablet ? <aside className="rail">{railContent}</aside> : null}

      <section className="workbench">
        <header className="topbar">
          <button
            className="methodology-btn rail-toggle-btn"
            onClick={openRailDrawer}
            aria-label="Open portfolio and access setup"
            title="Open portfolio and access setup"
          >
            <Menu size={18} />
          </button>
          <div>
            <p className="eyebrow">Live workbench</p>
            <h2>Hypothetical stress workbench</h2>
          </div>
          <div className="status-strip">
            <span className="status-chip">{access?.access_mode ?? "loading"}</span>
            <span className="status-chip portfolio-name" title={selectedPortfolio?.name}>
              {selectedPortfolio?.name ?? "No portfolio"}
            </span>
            {isAdmin ? (
              <button
                className="methodology-btn"
                onClick={openOpsDrawer}
                title="Operations console"
                aria-label="Open operations console"
              >
                <Activity size={16} />
              </button>
            ) : null}
            <button
              className="methodology-btn"
              onClick={commandPalette.open}
              title="Command palette (Ctrl/⌘ + K)"
              aria-label="Open command palette"
            >
              <Command size={16} />
            </button>
            <button
              className="methodology-btn"
              onClick={() => openMethodology()}
              title="Open methodology"
              aria-label="Open methodology"
            >
              <BookOpen size={16} />
            </button>
          </div>
        </header>

        <div className="notice">
          Hypothetical stress tool; not a forecast, not investment advice, not regulatory stress
          testing, not a substitute for institutional risk management.
        </div>

        {sessionExpired && !isAdmin ? (
          <div className="notice session-banner" role="alert">
            <span>Admin session expired — unlock again to continue using admin features.</span>
            <button type="button" className="ghost-button" onClick={focusUnlock}>
              Unlock
            </button>
          </div>
        ) : null}

        {error ? (
          <ErrorNotice error={error} onRetry={retryLastAction} onUnlock={focusUnlock} />
        ) : null}

        <ScenarioPanel
          access={access}
          scenarios={scenarios}
          scenarioKey={scenarioKey}
          scenarioDraftMode={scenarioDraftMode}
          onSelectScenario={handleScenarioSeed}
          onSetCustomMode={() => setScenarioDraftMode("custom")}
          scenarioText={scenarioText}
          setScenarioText={handleScenarioTextChange}
          selectedScenario={selectedScenario}
          isRunning={isRunning}
          onRun={handleRun}
          asOfDate={asOfDate}
          setAsOfDate={setAsOfDate}
          latestClose={access?.latest_market_date ?? ""}
        />

        {resultEnvelope?.result.narrative_mode === "analog_only" ? (
          <BackdatedModeBanner
            effectiveDate={resultEnvelope.result.market_date}
            requestedDate={
              resultEnvelope.result.requested_as_of_date ?? resultEnvelope.result.market_date
            }
          />
        ) : null}

        {isRunning ? (
          <RunProgress
            currentStage={currentStage}
            stageStatus={stageStatus}
            completedStages={completedStages}
            cacheHit={cacheHit}
            onCancel={handleCancelRun}
          />
        ) : null}

        <ResultsPanel
          envelope={resultEnvelope}
          attributionMethod={attributionMethod}
          setAttributionMethod={setAttributionMethod}
          factorMeta={factorMeta}
          displayMode={displayMode}
          setDisplayMode={setDisplayMode}
          navInput={navInput}
          setNavInput={setNavInput}
          valuationSort={valuationSort}
          setValuationSort={setValuationSort}
          isRunning={isRunning}
          isStale={isRunning && resultEnvelope != null}
          scrollRef={resultsRef}
          sampleScenarios={scenarios}
          onSeedScenario={handleScenarioSeed}
          bookProfile={bookProfile}
          profileBusy={profileBusy}
          onProfileBook={handleProfileBook}
          profileUnavailableReason={
            portfolioMode === "custom" && customUnits === "shares"
              ? "Book profile needs weights — switch the custom editor to Weights."
              : null
          }
          canDecompose={Boolean(isAdmin && resultEnvelope)}
          isDecomposing={isDecomposing}
          decomposeProgress={decomposeProgress}
          onDecompose={handleDecompose}
          onCancelDecompose={handleCancelDecompose}
          onOpenMethodology={openMethodology}
          canSave={Boolean(isAdmin && resultEnvelope?.reproducibility)}
          onSave={saveDialog.open}
        />

        {resultEnvelope &&
        canonicalSnapshot &&
        access?.permissions.free_text_scenario &&
        resultEnvelope.cache_key ? (
          <AdjustmentPanel
            envelope={resultEnvelope}
            canonicalSnapshot={canonicalSnapshot}
            factorMeta={factorMeta}
            onResult={handleAdjustmentResult}
            prefillRerun={handlePrefillRerun}
            onForbidden={() => void refreshAccess().catch(() => {})}
          />
        ) : null}

        {isAdmin ? (
          <SavedScenariosPanel
            key={`saved-${adminDataEpoch}`}
            reloadKey={savedReloadKey}
            onOpen={(env) => {
              setResultEnvelope(env);
              setCanonicalSnapshot(env.result);
              setAttributionMethod(preferredAttributionMethod(env.result));
            }}
            onForbidden={() => void refreshAccess().catch(() => {})}
          />
        ) : null}

        {isAdmin ? (
          <PortfolioHistoryPanel
            key={`portfolio-history-${adminDataEpoch}`}
            onForbidden={() => void refreshAccess().catch(() => {})}
            currentHoldings={
              portfolioMode === "custom" ? holdingsFromRows(customRows) : {}
            }
            snapshotDisabledReason={
              portfolioMode === "custom" && customUnits === "shares"
                ? "Snapshots store weights — switch the editor to Weights mode to snapshot this book."
                : undefined
            }
            onLoadSnapshot={(snap) => {
              setPortfolioMode("custom");
              setCustomName(`Snapshot ${snap.as_of_date}`);
              setCustomRows(
                Object.entries(snap.holdings).map(([ticker, weight], i) => ({
                  id: `snap-${snap.id}-${i}`,
                  ticker,
                  weight: String(weight)
                }))
              );
            }}
          />
        ) : null}
      </section>

      {resultEnvelope?.reproducibility ? (
        <SaveScenarioDialog
          isOpen={saveDialog.isOpen}
          onClose={saveDialog.close}
          onSaved={() => {
            saveDialog.close();
            setSavedReloadKey((k) => k + 1);
            pushToast({ variant: "success", message: "Scenario saved to library." });
          }}
          onForbidden={() => void refreshAccess().catch(() => {})}
          result={resultEnvelope.result}
          analogEvents={resultEnvelope.analog_events}
          reproducibility={resultEnvelope.reproducibility}
        />
      ) : null}

      <RailDrawer isOpen={railDrawer.isOpen} onClose={railDrawer.close}>
        {railContent}
      </RailDrawer>

      {isAdmin ? (
        <OpsDrawer
          isOpen={opsDrawer.isOpen}
          onClose={opsDrawer.close}
          onRequestPurge={requestPurge}
          onForbidden={() => void refreshAccess().catch(() => {})}
        />
      ) : null}

      <ConfirmDialog
        isOpen={purgeConfirm.isOpen}
        onClose={purgeConfirm.close}
        onConfirm={handlePurgeConfirmed}
        title="Purge all saved data"
        body={
          <p>
            This permanently deletes <strong>all</strong> saved scenarios, portfolios, and
            snapshots. The audit log is preserved. This cannot be undone.
          </p>
        }
        confirmLabel="Purge everything"
        danger
        typeToConfirm="DELETE"
        busy={purgeBusy}
      />

      <MethodologyDrawer
        markdown={methodology}
        isOpen={methodologyDrawer.isOpen}
        initialSection={methodologyDrawer.initialSection}
        onClose={methodologyDrawer.close}
      />

      <CommandPalette
        isOpen={commandPalette.isOpen}
        onClose={commandPalette.close}
        actions={commandActions}
      />
    </main>
  );
}

function AccessPanel({
  access,
  onAccessChange,
  passcodeInputRef
}: {
  access: AccessResponse | null;
  onAccessChange: (access: AccessResponse, opts?: { intentional?: boolean }) => void;
  passcodeInputRef?: RefObject<HTMLInputElement>;
}) {
  const [passcode, setPasscode] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<ApiError | string | null>(null);
  const isAdmin = access?.access_mode === "admin";

  async function handleUnlock() {
    setBusy(true);
    setMessage(null);
    try {
      const response = await unlock(passcode);
      onAccessChange(response, { intentional: true });
      setPasscode("");
    } catch (exc) {
      setMessage(toApiError(exc));
    } finally {
      setBusy(false);
    }
  }

  async function handleLock() {
    setBusy(true);
    try {
      const response = await lock();
      // A deliberate lock must not raise the session-expired banner.
      onAccessChange(response, { intentional: true });
    } catch (exc) {
      setMessage(toApiError(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel access-panel">
      <div className="panel-title">
        {isAdmin ? <Unlock size={16} /> : <Lock size={16} />}
        <span>{isAdmin ? "Admin mode" : "Visitor mode"}</span>
      </div>
      <p className="muted">
        {isAdmin
          ? "Unrestricted controls are enabled for this browser session."
          : "Visitors can run sample scenarios on sample portfolios only."}
      </p>
      {isAdmin ? (
        <button className="ghost-button" onClick={handleLock} disabled={busy}>
          <LogOut size={15} /> Return to visitor mode
        </button>
      ) : (
        <div className="unlock-row">
          <input
            ref={passcodeInputRef}
            value={passcode}
            onChange={(event) => setPasscode(event.target.value)}
            type="password"
            placeholder="Admin passcode"
            aria-label="Admin passcode"
            aria-invalid={Boolean(message)}
            aria-describedby={message ? "unlock-message" : undefined}
            disabled={!access?.admin_available || busy}
          />
          <button onClick={handleUnlock} disabled={!passcode || busy || !access?.admin_available}>
            <Shield size={15} /> Unlock
          </button>
        </div>
      )}
      {message ? <ErrorNotice variant="inline" error={message} id="unlock-message" /> : null}
    </section>
  );
}

function PortfolioPanel({
  access,
  portfolios,
  portfolioKey,
  setPortfolioKey,
  portfolioMode,
  setPortfolioMode,
  customName,
  setCustomName,
  customRows,
  setCustomRows,
  customUnits,
  setCustomUnits,
  customBenchmark,
  setCustomBenchmark
}: {
  access: AccessResponse | null;
  portfolios: SamplePortfolio[];
  portfolioKey: string;
  setPortfolioKey: (key: string) => void;
  portfolioMode: PortfolioMode;
  setPortfolioMode: (mode: PortfolioMode) => void;
  customName: string;
  setCustomName: (name: string) => void;
  customRows: HoldingRow[];
  setCustomRows: (rows: HoldingRow[]) => void;
  customUnits: "weights" | "shares";
  setCustomUnits: (units: "weights" | "shares") => void;
  customBenchmark: string;
  setCustomBenchmark: (ticker: string) => void;
}) {
  const selected = portfolios.find((portfolio) => portfolio.key === portfolioKey);
  const hasCash = customRows.some((row) => normalizeTicker(row.ticker) === "CASH");
  const [validation, setValidation] = useState<string[]>([]);
  const isShares = customUnits === "shares";

  async function validateCustom(rows = customRows) {
    // Shares mode is validated server-side (raw share counts, no sum-to-1 rule).
    if (isShares) return;
    try {
      const response = await validatePortfolio(holdingsFromRows(rows));
      setValidation(response.errors);
    } catch (exc) {
      setValidation([toApiError(exc).message]);
    }
  }

  async function handleCsv(file: File | null) {
    if (!file) return;
    const rows = parseCsv(await file.text());
    setCustomRows(rows);
    await validateCustom(rows);
  }

  const admin = Boolean(access?.permissions.custom_portfolio);
  return (
    <section className="panel">
      <div className="panel-title">
        <Table2 size={16} />
        <span>Portfolio</span>
      </div>
      {admin ? (
        <div className="segmented">
          <button
            className={portfolioMode === "sample" ? "active" : ""}
            onClick={() => setPortfolioMode("sample")}
          >
            Sample
          </button>
          <button
            className={portfolioMode === "custom" ? "active" : ""}
            onClick={() => setPortfolioMode("custom")}
          >
            Custom
          </button>
        </div>
      ) : null}

      {portfolioMode === "sample" || !admin ? (
        <>
          <label>
            Sample book
            <select value={portfolioKey} onChange={(event) => setPortfolioKey(event.target.value)}>
              {portfolios.map((portfolio) => (
                <option key={portfolio.key} value={portfolio.key}>
                  {portfolio.name}
                </option>
              ))}
            </select>
          </label>
          <p className="muted">{selected?.description}</p>
          {selected?.benchmark ? (
            <p className="muted">
              Benchmark: <code>{selected.benchmark}</code>
            </p>
          ) : null}
          <MiniHoldings holdings={selected?.holdings ?? {}} />
        </>
      ) : (
        <>
          <label>
            Portfolio name
            <input value={customName} onChange={(event) => setCustomName(event.target.value)} />
          </label>
          <label>
            Benchmark (optional)
            <input
              value={customBenchmark}
              onChange={(event) => setCustomBenchmark(normalizeTicker(event.target.value))}
              placeholder="e.g. SPY, QQQ, URTH"
              aria-label="Benchmark ticker"
            />
          </label>
          <div className="segmented" role="radiogroup" aria-label="Holding units">
            <button
              role="radio"
              aria-checked={!isShares}
              className={!isShares ? "active" : ""}
              onClick={() => setCustomUnits("weights")}
            >
              Weights
            </button>
            <button
              role="radio"
              aria-checked={isShares}
              className={isShares ? "active" : ""}
              onClick={() => setCustomUnits("shares")}
              title="Mark-to-market: enter share counts; nami marks each position to the as-of close and converts to USD"
            >
              Shares (MTM)
            </button>
          </div>
          <div className="upload-control">
            <Upload size={15} />
            <input
              type="file"
              accept=".csv,text/csv"
              aria-label="Upload holdings CSV"
              onChange={(e) => handleCsv(e.target.files?.[0] ?? null)}
            />
          </div>
          <div className="holding-editor">
            <div className="holding-row holding-row-head" aria-hidden="true">
              <span>Ticker</span>
              <span>{isShares ? "Shares" : "Weight"}</span>
            </div>
            {customRows.map((row, index) => (
              <div className="holding-row" key={row.id}>
                <input
                  value={row.ticker}
                  onChange={(event) => {
                    const next = [...customRows];
                    next[index] = { ...row, ticker: normalizeTicker(event.target.value) };
                    setCustomRows(next);
                  }}
                  placeholder="Ticker"
                  aria-label={`Ticker for holding ${index + 1}`}
                />
                <input
                  value={row.weight}
                  onChange={(event) => {
                    const next = [...customRows];
                    next[index] = { ...row, weight: event.target.value };
                    setCustomRows(next);
                  }}
                  placeholder={isShares ? "100" : "0.25"}
                  inputMode={isShares ? "numeric" : "decimal"}
                  aria-label={`${isShares ? "Shares" : "Weight"} for holding ${index + 1}`}
                />
              </div>
            ))}
          </div>
          <div className="button-row">
            <button
              className="ghost-button"
              onClick={() =>
                setCustomRows([
                  ...customRows,
                  { id: `row-${crypto.randomUUID()}`, ticker: "", weight: "0" }
                ])
              }
            >
              Add row
            </button>
            <button
              className="ghost-button"
              disabled={hasCash}
              title={
                isShares
                  ? "Add a cash sleeve (USD amount, not shares)"
                  : "Add a cash sleeve (zero-exposure weight)"
              }
              onClick={() =>
                setCustomRows([
                  ...customRows,
                  { id: `row-${crypto.randomUUID()}`, ticker: "CASH", weight: "0" }
                ])
              }
            >
              Add cash
            </button>
            {!isShares ? (
              <button className="ghost-button" onClick={() => validateCustom()}>
                Validate
              </button>
            ) : null}
          </div>
          {isShares ? (
            <p className="muted">
              Enter share counts. nami marks each position to the as-of close, converts to USD,
              and derives weights — true mark-to-market.
            </p>
          ) : validation.length ? (
            <div className="inline-error" role="alert">
              {validation.join(" ")}
            </div>
          ) : (
            <p className="muted">Weights may be decimals near 1.0 or percentages near 100.</p>
          )}
        </>
      )}
    </section>
  );
}

export function ScenarioPanel({
  access,
  scenarios,
  scenarioKey,
  scenarioDraftMode,
  onSelectScenario,
  onSetCustomMode,
  scenarioText,
  setScenarioText,
  selectedScenario,
  isRunning,
  onRun,
  asOfDate,
  setAsOfDate,
  latestClose
}: {
  access: AccessResponse | null;
  scenarios: SampleScenario[];
  scenarioKey: string;
  scenarioDraftMode: ScenarioDraftMode;
  onSelectScenario: (key: string) => void;
  onSetCustomMode: () => void;
  scenarioText: string;
  setScenarioText: (text: string) => void;
  selectedScenario?: SampleScenario;
  isRunning: boolean;
  onRun: () => void;
  asOfDate: string;
  setAsOfDate: (v: string) => void;
  latestClose: string;
}) {
  const isAdmin = access?.access_mode === "admin";
  const canEditText = Boolean(access);
  const chipScenarios = scenarios;
  const seededFrom =
    scenarioDraftMode === "custom" && selectedScenario ? selectedScenario.name : null;
  const runDisabled = isRunning || !scenarioText.trim();
  return (
    <section className="scenario-card">
      <div>
        <p className="eyebrow">Scenario</p>
        <h3>{isAdmin ? "Author or seed a stress narrative" : "Explore a stress narrative"}</h3>
      </div>
      {chipScenarios.length ? (
        <div className="scenario-chips" role="group" aria-label="Example scenarios">
          {chipScenarios.map((scenario) => (
            <button
              key={scenario.key}
              type="button"
              className={`chip${
                scenarioDraftMode === "sample" && scenario.key === scenarioKey ? " active" : ""
              }`}
              onClick={() => onSelectScenario(scenario.key)}
              title={scenario.text}
            >
              {scenario.name}
            </button>
          ))}
          <button
            type="button"
            className={`chip${scenarioDraftMode === "custom" ? " active" : ""}`}
            onClick={onSetCustomMode}
          >
            Custom
          </button>
        </div>
      ) : null}
      <div className="scenario-grid visitor-scenario-grid">
        <label className="scenario-text">
          Scenario text {seededFrom ? <span className="field-note">Seeded from {seededFrom}</span> : null}
          <textarea
            className="scenario-text-input"
            value={scenarioText}
            onChange={(event) => setScenarioText(event.target.value)}
            disabled={!canEditText}
            placeholder="Describe a hypothetical market stress."
          />
        </label>
      </div>
      {isAdmin ? (
        <AsOfDatePicker
          value={asOfDate}
          latestClose={latestClose}
          onChange={setAsOfDate}
          disabled={isRunning}
        />
      ) : null}
      <button className="primary-button" onClick={onRun} disabled={runDisabled}>
        {isRunning ? "Running pipeline..." : "Run hypothetical stress"} <ArrowRight size={16} />
      </button>
    </section>
  );
}

function ExposureBreakdown({ result }: { result: ScenarioResult }) {
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
    <div className="result-card exposure-card">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Exposure</p>
          <h3>{dimension === "sector" ? "Sector" : "Country"} breakdown</h3>
        </div>
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
      </div>
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
    </div>
  );
}

export function ResultsPanel({
  envelope,
  attributionMethod,
  setAttributionMethod,
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
  sampleScenarios = [],
  onSeedScenario,
  bookProfile = null,
  profileBusy = false,
  onProfileBook,
  profileUnavailableReason = null,
  canDecompose,
  isDecomposing,
  decomposeProgress,
  onDecompose,
  onCancelDecompose,
  onOpenMethodology,
  canSave,
  onSave
}: {
  envelope: ScenarioRunResponse | null;
  attributionMethod: AttributionMethod;
  setAttributionMethod: (method: AttributionMethod) => void;
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
  sampleScenarios?: SampleScenario[];
  onSeedScenario?: (key: string) => void;
  // Free pre-scenario book profile (renders in the empty state only).
  bookProfile?: BookProfile | null;
  profileBusy?: boolean;
  onProfileBook?: () => void;
  profileUnavailableReason?: string | null;
  canDecompose: boolean;
  isDecomposing: boolean;
  decomposeProgress: { done: number; total: number } | null;
  onDecompose: () => void;
  onCancelDecompose?: () => void;
  onOpenMethodology: (section?: string) => void;
  canSave: boolean;
  onSave: () => void;
}) {
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
          <ol className="empty-steps">
            <li>Pick a portfolio in the rail — sample books work in visitor mode.</li>
            <li>Describe a hypothetical stress above, or seed an example below.</li>
            <li>Run it: nami grounds a narrative, derives factor shocks, and attributes modeled P&L.</li>
          </ol>
          {sampleScenarios.length && onSeedScenario ? (
            <div className="scenario-chips empty-chips" role="group" aria-label="Try a sample scenario">
              {sampleScenarios.slice(0, 3).map((scenario) => (
                <button
                  key={scenario.key}
                  type="button"
                  className="chip"
                  onClick={() => onSeedScenario(scenario.key)}
                  title={scenario.text}
                >
                  {scenario.name}
                </button>
              ))}
            </div>
          ) : null}
          {onProfileBook ? (
            <div className="book-profile-cta">
              <button
                type="button"
                className="ghost-button"
                onClick={onProfileBook}
                disabled={profileBusy || Boolean(profileUnavailableReason)}
              >
                {profileBusy ? "Profiling book…" : "Profile this book — free, no LLM"}
              </button>
              {profileUnavailableReason ? (
                <span className="field-note">{profileUnavailableReason}</span>
              ) : null}
            </div>
          ) : null}
          {bookProfile ? <BookProfileCard profile={bookProfile} factorMeta={factorMeta} /> : null}
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
  const waterfall =
    showDollars && nav != null
      ? buildWaterfallDataDollars(result, attributionMethod, nav, currency, factorMeta)
      : buildWaterfallData(result, attributionMethod, factorMeta);
  const factorRows = factorReasoningRows(result, attributionMethod, factorMeta);
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
  const hasConditional = Boolean(result.portfolio_pnl.by_factor_conditional_shapley);
  const hasConditionalExplicit = Boolean(
    result.portfolio_pnl.by_factor_conditional_shapley_explicit
  );
  const hasConditionalGrouped = Boolean(
    result.portfolio_pnl.by_factor_conditional_shapley_grouped
  );
  const peripheryTotal = Object.values(result.portfolio_pnl.by_ticker_periphery).reduce(
    (acc, value) => acc + value,
    0
  );
  const isPhone = useMediaQuery("(max-width: 640px)");
  // Viewport-height bands: phone keeps the 320/-90°-ticks contract; short
  // laptops drop to 360; tall monitors get 480 instead of wasting space.
  const isShortViewport = useMediaQuery("(max-height: 720px)");
  const isTallViewport = useMediaQuery("(min-height: 900px)");
  const chartHeight = isPhone ? 320 : isShortViewport ? 360 : isTallViewport ? 480 : 420;
  const theme = chartTheme();
  const [reproCopied, setReproCopied] = useState(false);
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

  const attributionOptions: {
    method: AttributionMethod;
    label: string;
    title: string;
    disabled: boolean;
  }[] = [
    {
      method: "naive",
      label: "Naive algebra",
      title: "Direct algebraic attribution. Useful for audit/debug; assumes factor independence.",
      disabled: false
    },
    {
      method: "conditional",
      label: "Full conditional diagnostic",
      title:
        "Correlation-credit diagnostic under the full historical joint distribution. Non-causal; can credit unshocked factors.",
      disabled: !hasConditional
    },
    {
      method: "conditional_explicit",
      label: "Scenario shocks",
      title:
        "Production risk view restricted to factors explicitly shocked by the scenario. Unshocked factors stay at zero.",
      disabled: !hasConditionalExplicit
    },
    {
      method: "conditional_grouped",
      label: "Group totals",
      title:
        "Waterfall group totals for market / sector / style / macro, with factor-level detail kept in the table.",
      disabled: !hasConditionalGrouped
    }
  ];
  const mainAttributionOptions = attributionOptions.filter(
    (option) => option.method === "conditional_explicit" || option.method === "conditional_grouped"
  );
  const diagnosticOptions = attributionOptions
    .filter((option) => option.method === "naive" || option.method === "conditional")
    .map((option) =>
      option.method === "naive"
        ? {
            ...option,
            label: "Naive algebra",
            title:
              "Direct algebraic attribution. Useful for audit/debug; assumes factor independence."
          }
        : {
            ...option,
            label: "Full conditional diagnostic",
            title:
              "Correlation-credit diagnostic under the full historical joint distribution. Non-causal; can credit unshocked factors."
          }
    );

  // Roving-radiogroup arrow nav: move to the next/prev ENABLED option and select it.
  function moveAttribution(direction: 1 | -1) {
    setAttributionMethod(nextEnabledMethod(mainAttributionOptions, attributionMethod, direction));
  }

  function moveDiagnosticAttribution(direction: 1 | -1) {
    setAttributionMethod(nextEnabledMethod(diagnosticOptions, attributionMethod, direction));
  }

  return (
    <section
      ref={scrollRef}
      className={`results-stack${isStale ? " is-stale" : ""}`}
      aria-busy={isStale || undefined}
    >
      <ScenarioReadout
        result={result}
        attributionMethod={readoutMethod}
        factorMeta={factorMeta}
        showDollars={showDollars}
        nav={nav}
        currency={currency}
      />
      <AnalogReplayStrip
        result={result}
        analogEvents={analog_events}
        showDollars={showDollars}
        nav={nav}
        currency={currency}
      />
      <div className="results-toolbar">
        <div className="results-toolbar-left">
          {canSave ? (
            <button className="ghost-button" onClick={onSave}>
              <Save size={14} /> Save scenario
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
                placeholder="e.g. $1,000,000"
                inputMode="decimal"
                aria-label="Portfolio value (USD) for the dollar view"
              />
            </label>
          )}
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
      {hasNav ? (
        <div className="metric-grid secondary-metric-grid" aria-label="Portfolio value details">
          <Metric
            label="Portfolio NAV"
            value={formatCurrency(nav ?? 0, currency)}
            sub={
              stressedNav != null
                ? `-> ${formatCurrency(stressedNav, currency)} stressed`
                : undefined
            }
          />
        </div>
      ) : null}

      {/* ≥1440px the waterfall and exposure cards share a row (3fr/2fr) so wide
          screens carry more analytics instead of stretched single columns. */}
      <div className="result-card waterfall-card">
        <div className="card-heading">
          <div>
            <p className="eyebrow">Attribution</p>
            <h3>Systematic contribution waterfall</h3>
          </div>
          <div
            className="segmented"
            role="radiogroup"
            aria-label="Attribution method"
            onKeyDown={(event) => {
              if (event.key === "ArrowRight" || event.key === "ArrowDown") {
                event.preventDefault();
                moveAttribution(1);
              } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
                event.preventDefault();
                moveAttribution(-1);
              }
            }}
          >
            {mainAttributionOptions.map((option) => (
              <button
                key={option.method}
                role="radio"
                aria-checked={attributionMethod === option.method}
                tabIndex={attributionMethod === option.method ? 0 : -1}
                className={attributionMethod === option.method ? "active" : ""}
                onClick={() => setAttributionMethod(option.method)}
                disabled={option.disabled}
                title={option.title}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        <AttributionGuide onOpenMethodology={onOpenMethodology} />
        <AdvancedAttributionDiagnostics
          options={diagnosticOptions}
          attributionMethod={attributionMethod}
          setAttributionMethod={setAttributionMethod}
          moveAttribution={moveDiagnosticAttribution}
        />
        {attributionMethod === "conditional" ? (
          <div className="risk-diagnostics" role="note">
            <p className="eyebrow">Full conditional diagnostic</p>
            <p className="muted">
              Correlation credit, non-causal. Unshocked factors can receive positive or
              negative P&amp;L through historical co-movement; do not read those bars as
              explicit scenario shocks.
            </p>
          </div>
        ) : null}
        <RiskDiagnostics diagnostics={result.risk_diagnostics ?? []} factorMeta={factorMeta} />
        <Plot
          data={[
            {
              type: "waterfall",
              orientation: "v",
              x: waterfall.x,
              y: waterfall.y,
              measure: waterfall.measure,
              text: waterfall.text,
              hovertext: waterfall.hoverText,
              hovertemplate: "%{hovertext}<extra></extra>",
              textposition: "outside",
              connector: { line: { color: theme.connector } },
              increasing: { marker: { color: theme.up } },
              decreasing: { marker: { color: theme.down } },
              totals: { marker: { color: theme.total } }
            } as WaterfallTrace
          ]}
          layout={{
            autosize: true,
            height: chartHeight,
            paper_bgcolor: "rgba(0,0,0,0)",
            plot_bgcolor: "rgba(0,0,0,0)",
            font: { color: theme.text, family: theme.fontMono },
            margin: { l: 42, r: 18, t: 20, b: isPhone ? 110 : 70 },
            yaxis: {
              tickformat: showDollars ? "$,.0f" : ".1%",
              gridcolor: theme.grid
            },
            xaxis: {
              tickangle: isPhone ? -90 : -35,
              tickfont: isPhone ? { size: 9 } : undefined,
              automargin: true
            },
            showlegend: false
          }}
          config={{ displayModeBar: false, responsive: true }}
          useResizeHandler
          className="plot"
        />
      </div>

      <ExposureBreakdown result={result} />

      <div className="two-column">
        <TableCard
          title="Factor shocks and attribution"
          action={<ExportCsvButton label="Export factor shocks as CSV" onClick={exportFactorShocks} />}
        >
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
        </TableCard>
        <TableCard
          title="Name-level contribution"
          action={
            <ExportCsvButton label="Export name-level contribution as CSV" onClick={exportNameLevel} />
          }
        >
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
        </TableCard>
      </div>

      {hasNav ? (
        <section className="result-card">
          <div className="card-heading">
            <div>
              <p className="eyebrow">Valuation</p>
              <h3>Position valuation — original → stressed</h3>
            </div>
            <ExportCsvButton label="Export position valuation as CSV" onClick={exportValuations} />
          </div>
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
        </section>
      ) : null}

      <div className="two-column">
        <section className="result-card narrative">
          <h3>Grounded narrative</h3>
          <p>{result.narrative}</p>
          <div className="citation-list">
            {result.citations.map((citation) => (
              <a key={citation.url} href={citation.url} target="_blank" rel="noreferrer">
                {citation.title ?? citation.url}
              </a>
            ))}
          </div>
        </section>
        <TableCard
          title="Historical analogs"
          action={<ExportCsvButton label="Export historical analogs as CSV" onClick={exportAnalogs} />}
        >
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
        </TableCard>
      </div>

      <section className="result-card">
        <div className="card-heading">
          <div>
            <p className="eyebrow">Experimental</p>
            <h3>Fixed-context theme sensitivity</h3>
          </div>
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
        </div>
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
                        {formatSignedCurrency(contribution.shapley_value * (nav ?? 0), currency)}
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
            Admin-only · ~3–15 pipeline runs (~30–90s). The marginal shock each theme adds
            <em> within the original analog context</em> (analogs pinned, no re-grounding) — a
            theme-sensitivity view, illustrative, not causal. Current periphery total:{" "}
            {formatPercent(peripheryTotal)}.
          </p>
        )}
      </section>
    </section>
  );
}


function AdvancedAttributionDiagnostics({
  options,
  attributionMethod,
  setAttributionMethod,
  moveAttribution
}: {
  options: {
    method: AttributionMethod;
    label: string;
    title: string;
    disabled: boolean;
  }[];
  attributionMethod: AttributionMethod;
  setAttributionMethod: (method: AttributionMethod) => void;
  moveAttribution: (direction: 1 | -1) => void;
}) {
  return (
    <details
      className="advanced-diagnostics"
      open={attributionMethod === "naive" || attributionMethod === "conditional"}
    >
      <summary>Advanced attribution diagnostics</summary>
      <p className="muted">
        Audit/debug views only. Full conditional is correlation credit, non-causal, and can
        assign P&L to factors with no explicit scenario shock.
      </p>
      <div
        className="segmented"
        role="radiogroup"
        aria-label="Advanced attribution diagnostics"
        onKeyDown={(event) => {
          if (event.key === "ArrowRight" || event.key === "ArrowDown") {
            event.preventDefault();
            moveAttribution(1);
          } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
            event.preventDefault();
            moveAttribution(-1);
          }
        }}
      >
        {options.map((option) => (
          <button
            key={option.method}
            role="radio"
            aria-checked={attributionMethod === option.method}
            tabIndex={attributionMethod === option.method ? 0 : -1}
            className={attributionMethod === option.method ? "active" : ""}
            onClick={() => setAttributionMethod(option.method)}
            disabled={option.disabled}
            title={option.title}
          >
            {option.label}
          </button>
        ))}
      </div>
    </details>
  );
}

function RiskDiagnostics({
  diagnostics,
  factorMeta
}: {
  diagnostics: RiskDiagnosticRecord[];
  factorMeta: FactorMetadataMap;
}) {
  if (!diagnostics.length) return null;
  return (
    <div className="risk-diagnostics" role="note" aria-label="Risk diagnostics">
      <p className="eyebrow">Risk diagnostics</p>
      <ul>
        {diagnostics.map((diagnostic, index) => (
          <li key={`${diagnostic.kind}-${index}`} className={diagnostic.severity}>
            <strong>
              {diagnostic.factors.length
                ? diagnostic.factors.map((factor) => factorDisplayName(factorMeta, factor)).join(", ")
                : "Scenario"}
            </strong>
            <span>{diagnostic.message}</span>
            {Object.keys(diagnostic.evidence).length ? (
              <code>
                {Object.entries(diagnostic.evidence)
                  .map(([key, value]) =>
                    typeof value === "number"
                      ? `${key}: ${formatEvidence(value)}`
                      : `${key}: ${value}`
                  )
                  .join(" | ")}
              </code>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ScenarioReadout({
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
            <span
              className="readout-idio-band"
              title="±1σ idiosyncratic dispersion around the factor-driven point estimate, scaled to the median selected-analog horizon. A dispersion floor under independence assumptions — not a confidence interval on the scenario."
            >
              ±{" "}
              {showDollars && nav != null
                ? formatCurrency(nav * readout.idioBand, currency)
                : formatPercent(readout.idioBand)}{" "}
              idio (1σ)
              <span className="idio-band-note">dispersion floor — not a confidence interval</span>
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
            {readout.analogCount} analogs · {readout.citationCount} citations
          </span>
        </div>
      </div>
    </section>
  );
}

function BookProfileCard({
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
    <section className="result-card book-profile" aria-label="Book profile">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Book profile — engine only, no LLM</p>
          <h3>{profile.portfolio_name}</h3>
        </div>
        <span className="muted book-profile-asof">
          as of {profile.as_of} · {profile.n_factors} factors
        </span>
      </div>
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
        Portfolio beta per factor (Σ weight × beta; top {rows.length} of {profile.n_factors} by
        magnitude). ±{formatPercent(profile.idio_band_weekly)} weekly idio — a dispersion floor,
        not a confidence interval.
      </p>
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Ticker</th>
              <th className="num">Weight</th>
              <th className="num">R² adj</th>
              <th className="num">Weeks</th>
              <th className="num">Idio vol (wk)</th>
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
    </section>
  );
}

function AnalogReplayStrip({
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
  const rows = buildAnalogReplayRows(result, analogEvents);
  const replay = result.analog_replay;
  // Older cached/saved payloads carry no replay block — "not computed", never zero.
  if (!rows || !replay) return null;
  const fmt = (value: number) =>
    showDollars && nav != null
      ? formatSignedCurrency(nav * value, currency)
      : formatPercent(value);
  const tone = (value: number) => (value < 0 ? "down" : value > 0 ? "up" : "");
  return (
    <section className="analog-replay" aria-label="Analog replay range">
      <p className="readout-eyebrow">Analog replay range</p>
      <p className="replay-range">
        If this scenario plays out like the selected analogs did, this book's modeled move spans{" "}
        <strong className={tone(replay.min_pnl)}>{fmt(replay.min_pnl)}</strong> to{" "}
        <strong className={tone(replay.max_pnl)}>{fmt(replay.max_pnl)}</strong>
        {rows.length > 2 ? (
          <>
            {" "}
            (median <strong className={tone(replay.median_pnl)}>{fmt(replay.median_pnl)}</strong>)
          </>
        ) : null}
        .
      </p>
      <ul className="replay-events">
        {rows.map((row) => (
          <li key={row.eventId}>
            <span className="replay-event-name">{row.name}</span>
            <span className={`replay-event-pnl ${tone(row.pnl)}`}>{fmt(row.pnl)}</span>
            <span className="replay-coverage">
              {row.covered}/{row.total} factors
            </span>
          </li>
        ))}
      </ul>
      <p className="replay-caption">
        Each analog's realized factor moves pushed through this book's current betas. Factor-model
        only — excludes single-name (periphery) and idiosyncratic effects. Historical replay, not a
        forecast.
      </p>
    </section>
  );
}

function MiniHoldings({ holdings }: { holdings: Record<string, number> }) {
  return (
    <div className="mini-holdings">
      {Object.entries(holdings)
        .slice(0, 8)
        .map(([ticker, weight]) => (
          <span key={ticker}>
            {ticker} {formatPercent(weight, 1)}
          </span>
        ))}
    </div>
  );
}

function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {sub ? <small>{sub}</small> : null}
    </div>
  );
}

/** Sortable column header with aria-sort semantics; `numeric` right-aligns to
 * match `td.num` cells. */
function SortableTh({
  label,
  active,
  dir,
  onToggle,
  numeric = false
}: {
  label: string;
  active: boolean;
  dir: "asc" | "desc";
  onToggle: () => void;
  numeric?: boolean;
}) {
  const arrow = active ? (dir === "asc" ? "▲" : "▼") : "";
  return (
    <th
      className={`sortable${numeric ? " num" : ""}${active ? " sorted" : ""}`}
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <button type="button" onClick={onToggle}>
        {label}
        {arrow ? (
          <span className="sort-arrow" aria-hidden="true">
            {" "}
            {arrow}
          </span>
        ) : null}
      </button>
    </th>
  );
}

function ExportCsvButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      className="ghost-button table-export-btn"
      onClick={onClick}
      aria-label={label}
      title={label}
    >
      <Download size={13} /> CSV
    </button>
  );
}

function TableCard({
  title,
  action,
  children
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="result-card table-card">
      <div className="card-heading">
        <h3>{title}</h3>
        {action}
      </div>
      <TableScroll>{children}</TableScroll>
    </section>
  );
}
