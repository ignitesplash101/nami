import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import Plot from "react-plotly.js";
import {
  ArrowRight,
  BarChart3,
  BookOpen,
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
  decomposeScenario,
  getAccess,
  getMethodology,
  getSamplePortfolios,
  getSampleScenarios,
  lock,
  runScenarioStream,
  unlock,
  validatePortfolio
} from "./api";
import {
  buildWaterfallData,
  factorReasoningRows,
  formatPercent,
  topContributor
} from "./charts";
import { AdjustmentPanel } from "./AdjustmentPanel";
import { AsOfDatePicker, BackdatedModeBanner } from "./AsOfDatePicker";
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
  AttributionMethod,
  PortfolioSnapshotRecord,
  SamplePortfolio,
  SampleScenario,
  ScenarioResult,
  ScenarioRunResponse,
  SsePipelineStage
} from "./types";

type WaterfallTrace = {
  type: "waterfall";
  orientation: "v";
  x: string[];
  y: number[];
  measure: ("relative" | "total")[];
  text: string[];
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

const defaultCustomRows: HoldingRow[] = [
  { id: "row-aapl", ticker: "AAPL", weight: "0.5" },
  { id: "row-msft", ticker: "MSFT", weight: "0.5" }
];

function holdingsFromRows(rows: HoldingRow[]): Record<string, number> {
  const holdings: Record<string, number> = {};
  for (const row of rows) {
    const ticker = row.ticker.trim().toUpperCase();
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
    return { id: `csv-${index}-${ticker}`, ticker: ticker ?? "", weight: weight ?? "" };
  });
}

export default function App() {
  const [access, setAccess] = useState<AccessResponse | null>(null);
  const [portfolios, setPortfolios] = useState<SamplePortfolio[]>([]);
  const [scenarios, setScenarios] = useState<SampleScenario[]>([]);
  const [portfolioKey, setPortfolioKey] = useState("us_tech_growth");
  const [scenarioKey, setScenarioKey] = useState("china_tariffs");
  const [portfolioMode, setPortfolioMode] = useState<PortfolioMode>("sample");
  const [customName, setCustomName] = useState("Custom Book");
  const [customRows, setCustomRows] = useState<HoldingRow[]>(defaultCustomRows);
  const [scenarioText, setScenarioText] = useState("");
  // As-of date (YYYY-MM-DD). Empty string means today/live.
  const [asOfDate, setAsOfDate] = useState<string>("");
  const [resultEnvelope, setResultEnvelope] = useState<ScenarioRunResponse | null>(null);
  const [canonicalSnapshot, setCanonicalSnapshot] = useState<ScenarioResult | null>(null);
  const [savedReloadKey, setSavedReloadKey] = useState(0);
  const saveDialog = useOverlay();
  const [methodology, setMethodology] = useState("");
  const [attributionMethod, setAttributionMethod] = useState<AttributionMethod>("naive");
  const [isRunning, setIsRunning] = useState(false);
  const [isDecomposing, setIsDecomposing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentStage, setCurrentStage] = useState<SsePipelineStage | null>(null);
  const [stageStatus, setStageStatus] = useState<"start" | "done" | null>(null);
  const [completedStages, setCompletedStages] = useState<Set<SsePipelineStage>>(new Set());
  const [cacheHit, setCacheHit] = useState(false);
  const methodologyDrawer = useMethodologyDrawer();
  const railDrawer = useOverlay();
  const isMobileOrTablet = useMediaQuery("(max-width: 1079.98px)");

  function openMethodology(section?: string) {
    railDrawer.close();
    methodologyDrawer.open(section);
  }

  function openRailDrawer() {
    methodologyDrawer.close();
    railDrawer.open();
  }

  useEffect(() => {
    async function boot() {
      const [accessResponse, portfolioResponse, scenarioResponse, methodologyText] =
        await Promise.all([
          getAccess(),
          getSamplePortfolios(),
          getSampleScenarios(),
          getMethodology().catch(() => "")
        ]);
      setAccess(accessResponse);
      setPortfolios(portfolioResponse);
      setScenarios(scenarioResponse);
      setPortfolioKey(portfolioResponse[0]?.key ?? "us_tech_growth");
      setScenarioKey(scenarioResponse[0]?.key ?? "china_tariffs");
      setScenarioText(scenarioResponse[0]?.text ?? "");
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
    boot().catch((exc: Error) => setError(exc.message));
  }, []);

  useEffect(() => {
    const selected = scenarios.find((scenario) => scenario.key === scenarioKey);
    if (selected && access?.permissions.free_text_scenario) {
      setScenarioText(selected.text);
    }
  }, [access?.permissions.free_text_scenario, scenarioKey, scenarios]);

  const selectedPortfolio = useMemo(
    () => portfolios.find((portfolio) => portfolio.key === portfolioKey) ?? portfolios[0],
    [portfolioKey, portfolios]
  );
  const selectedScenario = useMemo(
    () => scenarios.find((scenario) => scenario.key === scenarioKey) ?? scenarios[0],
    [scenarioKey, scenarios]
  );

  const isAdmin = access?.access_mode === "admin";

  async function refreshAccess() {
    setAccess(await getAccess());
  }

  async function handleRun() {
    if (!access) return;
    setError(null);
    setIsRunning(true);
    setCurrentStage(null);
    setStageStatus(null);
    setCompletedStages(new Set());
    setCacheHit(false);
    try {
      const baseAdmin = {
        scenario_text: scenarioText || selectedScenario?.text,
        portfolio_key: portfolioMode === "sample" ? portfolioKey : undefined,
        portfolio_name: portfolioMode === "custom" ? customName : undefined,
        portfolio_holdings:
          portfolioMode === "custom" ? holdingsFromRows(customRows) : undefined,
        // Only thread as_of_date when admin chose a non-today date. Empty
        // string and today both mean "live" — let the backend default.
        as_of_date: asOfDate || undefined
      };
      const payload = access.permissions.free_text_scenario
        ? baseAdmin
        : {
            sample_scenario_key: scenarioKey,
            portfolio_key: portfolioKey
          };
      const response = await runScenarioStream(payload, (event) => {
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
      });
      setResultEnvelope(response);
      setCanonicalSnapshot(response.result);
      setAttributionMethod(
        response.result.portfolio_pnl.by_factor_conditional_shapley ? "conditional" : "naive"
      );
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setIsRunning(false);
    }
  }

  function handleAdjustmentResult(response: ScenarioRunResponse) {
    setResultEnvelope(response);
  }

  function handlePrefillRerun(text: string) {
    setScenarioText(text);
  }

  async function handleDecompose() {
    if (!resultEnvelope) return;
    setError(null);
    setIsDecomposing(true);
    try {
      const response = await decomposeScenario(resultEnvelope.result);
      setResultEnvelope(response);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setIsDecomposing(false);
    }
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
      <AccessPanel access={access} onAccessChange={setAccess} />
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
            <h2>Forward scenario propagation</h2>
          </div>
          <div className="status-strip">
            <span>{access?.access_mode ?? "loading"}</span>
            <span className="portfolio-name">{selectedPortfolio?.name ?? "No portfolio"}</span>
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
          Educational tool; not investment advice, not regulatory stress testing, not a substitute
          for institutional risk management.
        </div>

        {error ? <div className="error-banner">{error}</div> : null}

        <ScenarioPanel
          access={access}
          scenarios={scenarios}
          scenarioKey={scenarioKey}
          setScenarioKey={setScenarioKey}
          scenarioText={scenarioText}
          setScenarioText={setScenarioText}
          selectedScenario={selectedScenario}
          isRunning={isRunning}
          onRun={handleRun}
          asOfDate={asOfDate}
          setAsOfDate={setAsOfDate}
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
          />
        ) : null}

        <ResultsPanel
          envelope={resultEnvelope}
          attributionMethod={attributionMethod}
          setAttributionMethod={setAttributionMethod}
          canDecompose={Boolean(isAdmin && resultEnvelope)}
          isDecomposing={isDecomposing}
          onDecompose={handleDecompose}
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
            onResult={handleAdjustmentResult}
            prefillRerun={handlePrefillRerun}
          />
        ) : null}

        {isAdmin ? (
          <SavedScenariosPanel
            reloadKey={savedReloadKey}
            onOpen={(env) => {
              setResultEnvelope(env);
              setCanonicalSnapshot(env.result);
            }}
          />
        ) : null}

        {isAdmin ? (
          <PortfolioHistoryPanel
            currentHoldings={
              portfolioMode === "custom" ? holdingsFromRows(customRows) : {}
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
          }}
          result={resultEnvelope.result}
          analogEvents={resultEnvelope.analog_events}
          reproducibility={resultEnvelope.reproducibility}
        />
      ) : null}

      <RailDrawer isOpen={railDrawer.isOpen} onClose={railDrawer.close}>
        {railContent}
      </RailDrawer>

      <MethodologyDrawer
        markdown={methodology}
        isOpen={methodologyDrawer.isOpen}
        initialSection={methodologyDrawer.initialSection}
        onClose={methodologyDrawer.close}
      />
    </main>
  );
}

function AccessPanel({
  access,
  onAccessChange
}: {
  access: AccessResponse | null;
  onAccessChange: (access: AccessResponse) => void;
}) {
  const [passcode, setPasscode] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const isAdmin = access?.access_mode === "admin";

  async function handleUnlock() {
    setBusy(true);
    setMessage(null);
    try {
      const response = await unlock(passcode);
      onAccessChange(response);
      setPasscode("");
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  async function handleLock() {
    setBusy(true);
    const response = await lock();
    onAccessChange(response);
    setBusy(false);
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
      {message ? (
        <div className="inline-error" id="unlock-message" role="alert">
          {message}
        </div>
      ) : null}
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
  setCustomRows
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
}) {
  const selected = portfolios.find((portfolio) => portfolio.key === portfolioKey);
  const [validation, setValidation] = useState<string[]>([]);

  async function validateCustom(rows = customRows) {
    const response = await validatePortfolio(holdingsFromRows(rows));
    setValidation(response.errors);
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
          <MiniHoldings holdings={selected?.holdings ?? {}} />
        </>
      ) : (
        <>
          <label>
            Portfolio name
            <input value={customName} onChange={(event) => setCustomName(event.target.value)} />
          </label>
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
              <span>Weight</span>
            </div>
            {customRows.map((row, index) => (
              <div className="holding-row" key={row.id}>
                <input
                  value={row.ticker}
                  onChange={(event) => {
                    const next = [...customRows];
                    next[index] = { ...row, ticker: event.target.value };
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
                  placeholder="0.25"
                  inputMode="decimal"
                  aria-label={`Weight for holding ${index + 1}`}
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
            <button className="ghost-button" onClick={() => validateCustom()}>
              Validate
            </button>
          </div>
          {validation.length ? (
            <div className="inline-error" role="alert">{validation.join(" ")}</div>
          ) : (
            <p className="muted">Weights may be decimals near 1.0 or percentages near 100.</p>
          )}
        </>
      )}
    </section>
  );
}

function ScenarioPanel({
  access,
  scenarios,
  scenarioKey,
  setScenarioKey,
  scenarioText,
  setScenarioText,
  selectedScenario,
  isRunning,
  onRun,
  asOfDate,
  setAsOfDate
}: {
  access: AccessResponse | null;
  scenarios: SampleScenario[];
  scenarioKey: string;
  setScenarioKey: (key: string) => void;
  scenarioText: string;
  setScenarioText: (text: string) => void;
  selectedScenario?: SampleScenario;
  isRunning: boolean;
  onRun: () => void;
  asOfDate: string;
  setAsOfDate: (v: string) => void;
}) {
  const canFreeText = Boolean(access?.permissions.free_text_scenario);
  return (
    <section className="scenario-card">
      <div>
        <p className="eyebrow">Scenario</p>
        <h3>{canFreeText ? "Author or seed a market narrative" : "Select a visitor sample"}</h3>
      </div>
      <div className="scenario-grid">
        <label>
          Sample scenario
          <select value={scenarioKey} onChange={(event) => setScenarioKey(event.target.value)}>
            {scenarios.map((scenario) => (
              <option key={scenario.key} value={scenario.key}>
                {scenario.name}
              </option>
            ))}
          </select>
        </label>
        <label className="scenario-text">
          Scenario text
          <textarea
            value={canFreeText ? scenarioText : selectedScenario?.text ?? ""}
            onChange={(event) => setScenarioText(event.target.value)}
            disabled={!canFreeText}
            placeholder="Describe a forward-looking market scenario."
          />
        </label>
      </div>
      {canFreeText ? (
        <AsOfDatePicker value={asOfDate} onChange={setAsOfDate} disabled={isRunning} />
      ) : null}
      <button className="primary-button" onClick={onRun} disabled={isRunning || !selectedScenario}>
        {isRunning ? "Running pipeline..." : "Run scenario"} <ArrowRight size={16} />
      </button>
    </section>
  );
}

function ResultsPanel({
  envelope,
  attributionMethod,
  setAttributionMethod,
  canDecompose,
  isDecomposing,
  onDecompose,
  onOpenMethodology,
  canSave,
  onSave
}: {
  envelope: ScenarioRunResponse | null;
  attributionMethod: AttributionMethod;
  setAttributionMethod: (method: AttributionMethod) => void;
  canDecompose: boolean;
  isDecomposing: boolean;
  onDecompose: () => void;
  onOpenMethodology: (section?: string) => void;
  canSave: boolean;
  onSave: () => void;
}) {
  if (!envelope) {
    return (
      <section className="empty-results">
        <BarChart3 size={22} />
        <h3>No scenario run yet</h3>
        <p>Run a sample or admin scenario to populate P&L, attribution, citations, and analogs.</p>
      </section>
    );
  }
  const { result, analog_events } = envelope;
  const waterfall = buildWaterfallData(result, attributionMethod);
  const top = topContributor(result, attributionMethod);
  const factorRows = factorReasoningRows(result, attributionMethod);
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

  const attributionOptions: {
    method: AttributionMethod;
    label: string;
    title: string;
    disabled: boolean;
  }[] = [
    {
      method: "naive",
      label: "Naive",
      title: "(Σᵢ wᵢ·βᵢ,f) · shock[f] — credit only to factors the LLM shocked",
      disabled: false
    },
    {
      method: "conditional",
      label: "Conditional (full)",
      title:
        "Full F-dim Shapley under the historical conditional distribution. Can cross-credit correlated factors the LLM did not name.",
      disabled: !hasConditional
    },
    {
      method: "conditional_explicit",
      label: "Explicit-only",
      title:
        "Shapley restricted to factors the LLM explicitly shocked. Unshocked factors stay at zero. Sum ≤ factor-driven P&L.",
      disabled: !hasConditionalExplicit
    },
    {
      method: "conditional_grouped",
      label: "Grouped",
      title:
        "Shapley over factor groups (market / sector / style / macro), redistributed within-group by naive weight. Collapses within-group leakage.",
      disabled: !hasConditionalGrouped
    }
  ];

  // Roving-radiogroup arrow nav: move to the next/prev ENABLED option and select it.
  function moveAttribution(direction: 1 | -1) {
    setAttributionMethod(nextEnabledMethod(attributionOptions, attributionMethod, direction));
  }

  return (
    <section className="results-stack">
      <div className="results-toolbar">
        {canSave ? (
          <button className="ghost-button" onClick={onSave}>
            <Save size={14} /> Save scenario
          </button>
        ) : null}
        {envelope.reproducibility ? (
          <span className="muted reproducibility-chip">
            prompt {envelope.reproducibility.prompt_version} · model{" "}
            {envelope.reproducibility.model_id} · as-of{" "}
            <code>{envelope.reproducibility.effective_as_of_date}</code>
          </span>
        ) : null}
      </div>
      <div className="metric-grid">
        <Metric label="Portfolio P&L" value={formatPercent(result.portfolio_pnl.total_pnl)} />
        <Metric
          label="Top contributor"
          value={top.factor}
          sub={`${formatPercent(top.shockApplied, 1)} shock -> ${formatPercent(top.contribution)} P&L`}
        />
        <Metric label="Analogs" value={String(result.analogs_selected.length)} />
        <Metric label="Citations" value={String(result.citations.length)} />
      </div>

      <div className="result-card">
        <div className="card-heading">
          <div>
            <p className="eyebrow">Attribution</p>
            <h3>Factor contribution waterfall</h3>
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
            {attributionOptions.map((option) => (
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
        <Plot
          data={[
            {
              type: "waterfall",
              orientation: "v",
              x: waterfall.x,
              y: waterfall.y,
              measure: waterfall.measure,
              text: waterfall.text,
              textposition: "outside",
              connector: { line: { color: "rgba(233,216,166,0.3)" } },
              increasing: { marker: { color: "#4cc38a" } },
              decreasing: { marker: { color: "#e8615a" } },
              totals: { marker: { color: "#7fb5d6" } }
            } as WaterfallTrace
          ]}
          layout={{
            autosize: true,
            height: isPhone ? 320 : 420,
            paper_bgcolor: "rgba(0,0,0,0)",
            plot_bgcolor: "rgba(0,0,0,0)",
            font: { color: "#eef2ec", family: "IBM Plex Mono, monospace" },
            margin: { l: 42, r: 18, t: 20, b: isPhone ? 110 : 70 },
            yaxis: { tickformat: ".1%", gridcolor: "rgba(238,242,236,0.08)" },
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

      <div className="two-column">
        <TableCard title="Factor shocks and attribution">
          <table>
            <thead>
              <tr>
                <th>Factor</th>
                <th>Shock</th>
                <th>P&L contrib</th>
                <th>Reasoning</th>
              </tr>
            </thead>
            <tbody>
              {factorRows.map((row) => (
                <tr key={row.factor}>
                  <td>
                    <button
                      className="factor-link"
                      onClick={() => onOpenMethodology("factor-universe")}
                    >
                      {row.factor}
                    </button>
                  </td>
                  <td>{formatPercent(row.shockApplied)}</td>
                  <td>{formatPercent(row.contribution)}</td>
                  <td>{row.reasoning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableCard>
        <TableCard title="Name-level contribution">
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Weight</th>
                <th>Factor</th>
                <th>Periphery</th>
                <th>Total</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(result.portfolio_pnl.by_ticker_total)
                .sort((a, b) => a[1] - b[1])
                .map(([ticker, total]) => (
                  <tr key={ticker}>
                    <td>{ticker}</td>
                    <td>{formatPercent(result.portfolio_holdings[ticker] ?? 0)}</td>
                    <td>{formatPercent(result.portfolio_pnl.by_ticker_factor[ticker] ?? 0)}</td>
                    <td>{formatPercent(result.portfolio_pnl.by_ticker_periphery[ticker] ?? 0)}</td>
                    <td>{formatPercent(total)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </TableCard>
      </div>

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
        <TableCard title="Historical analogs">
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
            <h3>Narrative decomposition</h3>
          </div>
          <button className="ghost-button" onClick={onDecompose} disabled={!canDecompose || isDecomposing}>
            {isDecomposing ? "Running subset evaluations..." : "Run decomposition"}
          </button>
        </div>
        {result.narrative_shapley ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Sub-narrative</th>
                  <th>Shapley P&L</th>
                  <th>Relative</th>
                </tr>
              </thead>
              <tbody>
                {result.narrative_shapley.contributions.map((contribution) => (
                  <tr key={contribution.narrative_index}>
                    <td>{contribution.narrative_index + 1}</td>
                    <td>{contribution.narrative_text}</td>
                    <td>{formatPercent(contribution.shapley_value)}</td>
                    <td>{formatPercent(contribution.relative_contribution)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">
            Admin-only. Runs the full pipeline over each subset, so it is slow and experimental.
            Current periphery total: {formatPercent(peripheryTotal)}.
          </p>
        )}
      </section>
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

function TableCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="result-card table-card">
      <h3>{title}</h3>
      <div className="table-scroll">{children}</div>
    </section>
  );
}
