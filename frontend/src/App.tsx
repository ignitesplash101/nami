import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { Activity, BookOpen, Command, Menu, Moon, Sun } from "lucide-react";
import { useTheme } from "./theme";
import {
  ApiError,
  getAccess,
  getFactors,
  getMethodology,
  getSamplePortfolios,
  getSampleScenarios,
  getSavedScenario,
  lock,
  purgeAllData,
  toApiError
} from "./api";
import { ConfirmDialog } from "./ConfirmDialog";
import { ErrorNotice } from "./ErrorNotice";
import { OpsDrawer } from "./OpsDrawer";
import { scrollBehavior } from "./motion";
import { useToasts } from "./toast";
import {
  formatPercent,
  parseNav,
  sameScenarioResult
} from "./charts";
import { factorMap } from "./factors";
import { defaultCustomRows, holdingsFromRows } from "./holdings";
import type { HoldingRow, PortfolioMode, ScenarioDraftMode } from "./holdings";
import { BookArea } from "./panels/BookArea";
import { RailContent } from "./panels/RailContent";
import { ScenarioPanel } from "./panels/ScenarioPanel";
import { ScenarioWorkspace } from "./panels/ScenarioWorkspace";
import { ResultsPanel } from "./results/ResultsPanel";
import type { ResultsTabKey, ValuationSort } from "./results/ResultsPanel";
import { Tabs } from "./Tabs";
import type { TabItem } from "./Tabs";
import { useAccessSession } from "./state/useAccessSession";
import { useFreeAnalytics } from "./state/useFreeAnalytics";
import { useOverlayManager } from "./state/useOverlayManager";
import { useRunController } from "./state/useRunController";
import { BackdatedModeBanner } from "./AsOfDatePicker";
import { CommandPalette } from "./CommandPalette";
import type { CommandAction } from "./CommandPalette";
import { CollapsibleCard } from "./CollapsibleCard";
import { ComparisonPanel } from "./ComparisonPanel";
import { PortfolioHistoryPanel } from "./PortfolioHistoryPanel";
import { RailDrawer } from "./RailDrawer";
import { RunProgress, stageLabel } from "./RunProgress";
import { SaveScenarioDialog } from "./SaveScenarioDialog";
import { SavedScenariosPanel } from "./SavedScenariosPanel";
import { useMediaQuery } from "./useMediaQuery";
import { useOverlay } from "./useOverlay";
import type {
  FactorMetadataMap,
  SamplePortfolio,
  SampleScenario,
  ScenarioResult,
  ScenarioRunResponse
} from "./types";

// Lazy so react-markdown + the methodology renderer stay out of the first-load
// chunk; the drawer opens on click, so a one-frame Suspense gap is invisible.
const MethodologyDrawer = lazy(() =>
  import("./MethodologyDrawer").then((m) => ({ default: m.MethodologyDrawer }))
);

/** Top-level workbench areas. Persistent chrome (topbar, disclaimer, banners,
 * rail, footer) stays OUTSIDE the tabs; each area owns one job. */
type AreaKey = "scenario" | "book" | "library";

function initialArea(): AreaKey {
  if (typeof window === "undefined") return "scenario";
  const view = new URLSearchParams(window.location.search).get("view");
  return view === "book" ? "book" : view === "library" ? "library" : "scenario";
}

export default function App() {
  const { theme, toggleTheme } = useTheme();
  const { access, isAdmin, sessionExpired, applyAccess, refreshAccess } = useAccessSession();
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
  // Pin & compare: holds a full envelope for side-by-side comparison. No other
  // setter touches it, so it survives runs, adjustments, decompositions, and
  // saved-scenario opens until the user re-pins or clears it.
  const [pinnedEnvelope, setPinnedEnvelope] = useState<ScenarioRunResponse | null>(null);
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
  const [error, setError] = useState<ApiError | string | null>(null);
  const [bootSerial, setBootSerial] = useState(0);
  // Top-level area + results sub-tab; both persist across runs. The area
  // round-trips through ?view= so Book/Library views are linkable.
  const [activeArea, setActiveArea] = useState<AreaKey>(initialArea);
  const [resultsTab, setResultsTab] = useState<ResultsTabKey>("drivers");
  const lastFailedActionRef = useRef<"run" | "decompose" | "boot" | "profile" | "replay" | null>(
    null
  );
  const passcodeInputRef = useRef<HTMLInputElement>(null);
  // Guards the boot effect's default-selection seeding (see boot()) so a second
  // async wave can never clobber a selection the user has already made.
  const bootSeededRef = useRef(false);

  // Run/decompose stream machinery: stage state, sequence guards, cancels.
  // buildRunPayload / handleRunResult / reportError are hoisted declarations.
  const {
    isRunning,
    isDecomposing,
    decomposeProgress,
    currentStage,
    stageStatus,
    completedStages,
    cacheHit,
    runSerial,
    handleRun,
    handleCancelRun,
    handleDecompose,
    handleCancelDecompose
  } = useRunController({
    buildRunPayload,
    onRunResult: handleRunResult,
    getDecomposeSource: () => resultEnvelope?.result ?? null,
    onDecomposeResult: (response) => setResultEnvelope(response),
    onError: (exc, action) => reportError(exc, action),
    clearError: () => setError(null)
  });

  // Free pre-scenario surfaces (zero LLM); cleared on any book change.
  const {
    bookProfile,
    profileBusy,
    eventsReplay,
    replayBusy,
    handleProfileBook,
    handleEventsReplay
  } = useFreeAnalytics({
    portfolioKey,
    portfolioMode,
    customRows,
    customUnits,
    customName,
    onError: (exc, action) => reportError(exc, action),
    clearError: () => setError(null)
  });

  // Dynamic tab title: the headline P&L + a scenario snippet while a result is
  // on screen, so parked tabs stay identifiable. Reset when cleared.
  useEffect(() => {
    if (resultEnvelope) {
      const pnl = formatPercent(resultEnvelope.result.portfolio_pnl.total_pnl);
      const text = resultEnvelope.result.scenario_text.trim();
      const snippet = text.length > 40 ? `${text.slice(0, 39).trimEnd()}…` : text;
      document.title = `${pnl} · ${snippet} — nami`;
    } else {
      document.title = "nami — scenario explorer";
    }
  }, [resultEnvelope]);

  // One polite live region announces run lifecycle to screen readers with the
  // same stage labels the visual stepper shows. Completion announces the
  // headline; errors are announced by the toast/notice components themselves.
  const runAnnouncement = isRunning
    ? cacheHit
      ? "Loading cached result"
      : (currentStage && stageLabel(currentStage)) || "Running scenario"
    : resultEnvelope
      ? `Scenario complete: modeled portfolio P&L ${formatPercent(
          resultEnvelope.result.portfolio_pnl.total_pnl
        )}`
      : "";
  const resultsRef = useRef<HTMLElement>(null);
  const { push: pushToast } = useToasts();
  const {
    methodologyDrawer,
    methodologyMounted,
    railDrawer,
    commandPalette,
    opsDrawer,
    purgeConfirm,
    openMethodology,
    openRailDrawer,
    openOpsDrawer,
    openCommandPalette,
    requestPurge
  } = useOverlayManager();
  const [purgeBusy, setPurgeBusy] = useState(false);
  // Bumped on purge success and passed as `key` to the saved-scenarios +
  // portfolio-history panels: the backend purge deletes portfolios/snapshots
  // too, and those panels fetch on mount/selection only — a remount resets
  // their local state instead of leaving deleted records on screen.
  const [adminDataEpoch, setAdminDataEpoch] = useState(0);
  const isMobileOrTablet = useMediaQuery("(max-width: 1079.98px)");

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
      // Seed the DEFAULT selection exactly once per app life. Boot's async work
      // can complete in more than one wave (StrictMode double-invoke in dev,
      // connection-queued fetches), and a late wave re-running these setters
      // silently reverted any portfolio/scenario the user had already picked.
      if (!bootSeededRef.current) {
        bootSeededRef.current = true;
        setPortfolioKey(portfolioResponse[0]?.key ?? "us_tech_growth");
        setScenarioKey(scenarioResponse[0]?.key ?? "china_tariffs");
        setScenarioText(scenarioResponse[0]?.text ?? "");
        setScenarioDraftMode("sample");
      }
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

  // Keep ?view= linkable without a router: scenario is the clean default URL.
  useEffect(() => {
    const url = new URL(window.location.href);
    if (activeArea === "scenario") url.searchParams.delete("view");
    else url.searchParams.set("view", activeArea);
    window.history.replaceState(null, "", url);
  }, [activeArea]);

  // A visitor can deep-link ?view=library but never see it — snap back once
  // access resolves (the Library tab isn't rendered for visitors at all).
  useEffect(() => {
    if (access && !isAdmin && activeArea === "library") setActiveArea("scenario");
  }, [access, isAdmin, activeArea]);

  const selectedPortfolio = useMemo(
    () => portfolios.find((portfolio) => portfolio.key === portfolioKey) ?? portfolios[0],
    [portfolioKey, portfolios]
  );
  const selectedScenario = useMemo(
    () => scenarios.find((scenario) => scenario.key === scenarioKey) ?? scenarios[0],
    [scenarioKey, scenarios]
  );

  // Normalize any failure into an ApiError; cancelled runs stay silent and a
  // forbidden response triggers an access re-check (catches stale admin cookies).
  function reportError(
    exc: unknown,
    action: "run" | "decompose" | "boot" | "profile" | "replay" | null = null
  ) {
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
    else if (action === "profile") void handleProfileBook();
    else if (action === "replay") void handleEventsReplay();
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

  // The run payload the controller streams: admins send the full form;
  // visitors send free text on a sample book or a sample-scenario key.
  function buildRunPayload() {
    if (!access) return null;
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
    return isAdmin
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
  }

  // A completed RUN resets the canonical + attribution and surfaces dollars by
  // default when the run is marked (shares) OR a notional portfolio value is
  // already entered (sticky knob); otherwise stays in percent.
  function handleRunResult(response: ScenarioRunResponse) {
    setResultEnvelope(response);
    setCanonicalSnapshot(response.result);
    setDisplayMode(
      response.result.portfolio_nav != null || parseNav(navInput) != null ? "usd" : "pct"
    );
  }

  function handleAdjustmentResult(response: ScenarioRunResponse) {
    setResultEnvelope(response);
  }

  function handlePrefillRerun(text: string) {
    setScenarioText(text);
    setScenarioDraftMode("custom");
  }

  // Palette actions are a thin accelerator over already-visible controls. Built
  // fresh each render so the closures read current state (cheap; small list).
  const commandActions: CommandAction[] = [
    {
      id: "run",
      label: "Run scenario",
      hint: "Enter",
      run: () => {
        setActiveArea("scenario");
        void handleRun();
      }
    },
    { id: "area-scenario", label: "Go to Scenario", run: () => setActiveArea("scenario") },
    { id: "area-book", label: "Go to Your book", run: () => setActiveArea("book") },
    { id: "setup", label: "Open portfolio & access setup", run: openRailDrawer },
    { id: "methodology", label: "Open methodology", run: () => openMethodology() },
    {
      id: "theme",
      label: theme === "dark" ? "Switch to light theme" : "Switch to dark theme",
      run: toggleTheme
    }
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
      id: "area-library",
      label: "Go to Library",
      run: () => setActiveArea("library")
    });
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
    <RailContent
      access={access}
      onAccessChange={applyAccess}
      passcodeInputRef={passcodeInputRef}
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
      onOpenOperations={openOpsDrawer}
    />
  );

  const scenarioInput = (
    <>
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
          weightsAsOf={
            resultEnvelope.result.portfolio_key !== "custom"
              ? access?.sample_weights_as_of ?? null
              : null
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
    </>
  );

  const scenarioOutput = (
    <ResultsPanel
      envelope={resultEnvelope}
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
      onOpenBook={() => setActiveArea("book")}
      resultsTab={resultsTab}
      onResultsTabChange={setResultsTab}
      canAdjust={Boolean(access?.permissions.free_text_scenario)}
      canonicalSnapshot={canonicalSnapshot}
      onAdjustResult={handleAdjustmentResult}
      onPrefillRerun={handlePrefillRerun}
      onForbidden={() => void refreshAccess().catch(() => {})}
      canDecompose={Boolean(isAdmin && resultEnvelope)}
      isDecomposing={isDecomposing}
      decomposeProgress={decomposeProgress}
      onDecompose={handleDecompose}
      onCancelDecompose={handleCancelDecompose}
      onOpenMethodology={openMethodology}
      canSave={Boolean(isAdmin && resultEnvelope?.reproducibility)}
      onSave={saveDialog.open}
      onPin={() => setPinnedEnvelope(resultEnvelope)}
      isPinned={Boolean(
        pinnedEnvelope &&
          resultEnvelope &&
          sameScenarioResult(pinnedEnvelope.result, resultEnvelope.result)
      )}
    />
  );

  const scenarioArea = (
    <>
      <ScenarioWorkspace
        hasResults={resultEnvelope != null}
        input={scenarioInput}
        output={scenarioOutput}
      />

      {pinnedEnvelope &&
      resultEnvelope &&
      !sameScenarioResult(pinnedEnvelope.result, resultEnvelope.result) ? (
        <ComparisonPanel
          pinned={pinnedEnvelope}
          current={resultEnvelope}
          factorMeta={factorMeta}
          onUnpin={() => setPinnedEnvelope(null)}
        />
      ) : null}
    </>
  );

  const bookArea = (
    <BookArea
      selectedPortfolio={selectedPortfolio}
      isCustomBook={portfolioMode === "custom"}
      customName={customName}
      profile={bookProfile}
      replay={eventsReplay}
      profileBusy={profileBusy}
      replayBusy={replayBusy}
      onProfile={handleProfileBook}
      onReplay={handleEventsReplay}
      unavailableReason={
        portfolioMode === "custom" && customUnits === "shares"
          ? "The free book analytics need weights — switch the custom editor to Weights."
          : null
      }
      factorMeta={factorMeta}
    />
  );

  const libraryArea = (
    <>
      <CollapsibleCard
        className="panel-shell"
        eyebrow="Library"
        title="Saved scenarios"
        summary="browse, reopen, tag-filter"
      >
        <SavedScenariosPanel
          key={`saved-${adminDataEpoch}`}
          reloadKey={savedReloadKey}
          onOpen={(env) => {
            setResultEnvelope(env);
            setCanonicalSnapshot(env.result);
            // The opened result renders in the Scenario area — switch so it's visible.
            setActiveArea("scenario");
          }}
          onForbidden={() => void refreshAccess().catch(() => {})}
        />
      </CollapsibleCard>

      <CollapsibleCard
        className="panel-shell"
        eyebrow="Library"
        title="Saved portfolios & snapshots"
        summary="named books · dated snapshots"
      >
        <PortfolioHistoryPanel
          key={`portfolio-history-${adminDataEpoch}`}
          onForbidden={() => void refreshAccess().catch(() => {})}
          currentHoldings={portfolioMode === "custom" ? holdingsFromRows(customRows) : {}}
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
      </CollapsibleCard>
    </>
  );

  const areaItems: TabItem<AreaKey>[] = [
    { key: "scenario", label: "Scenario", content: scenarioArea, busy: isRunning || isDecomposing },
    { key: "book", label: "Your book", content: bookArea },
    ...(isAdmin ? [{ key: "library" as const, label: "Library", content: libraryArea }] : [])
  ];
  const effectiveArea: AreaKey = areaItems.some((item) => item.key === activeArea)
    ? activeArea
    : "scenario";

  return (
    <main className="app-shell">
      <a className="skip-link" href="#workbench">
        Skip to workbench
      </a>
      <div className="visually-hidden" role="status" aria-live="polite">
        {runAnnouncement}
      </div>
      {!isMobileOrTablet ? <aside className="rail">{railContent}</aside> : null}

      <section className="workbench" id="workbench">
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
            <p className="eyebrow">What-if stress scenarios</p>
            <h1>Portfolio scenario explorer</h1>
          </div>
          <div className="status-strip">
            <span className="status-chip access-mode-chip">
              {access ? (isAdmin ? "admin" : "Demo mode") : "loading"}
            </span>
            <span className="status-chip portfolio-name" title={selectedPortfolio?.name}>
              {selectedPortfolio?.name ?? "No portfolio"}
            </span>
            {isAdmin ? (
              <button
                className="methodology-btn ops-btn"
                onClick={openOpsDrawer}
                title="Operations console"
                aria-label="Open operations console"
              >
                <Activity size={16} />
              </button>
            ) : null}
            <button
              className="methodology-btn cmdk-btn"
              onClick={openCommandPalette}
              title="Command palette (Ctrl/⌘ + K)"
              aria-label="Open command palette"
            >
              <Command size={16} />
            </button>
            <button
              className="methodology-btn"
              onClick={toggleTheme}
              title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
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

        <Tabs
          className="area-tabs"
          idBase="area"
          ariaLabel="Workbench areas"
          items={areaItems}
          active={effectiveArea}
          onChange={setActiveArea}
        />

        <footer className="app-footer">
          nami — scenario explorer · educational/research use only
        </footer>
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

      {methodologyMounted ? (
        <Suspense fallback={null}>
          <MethodologyDrawer
            markdown={methodology}
            isOpen={methodologyDrawer.isOpen}
            initialSection={methodologyDrawer.initialSection}
            onClose={methodologyDrawer.close}
          />
        </Suspense>
      ) : null}

      <CommandPalette
        isOpen={commandPalette.isOpen}
        onClose={commandPalette.close}
        actions={commandActions}
      />
    </main>
  );
}
