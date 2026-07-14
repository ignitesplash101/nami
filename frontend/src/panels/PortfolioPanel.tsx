import { useRef, useState } from "react";
import type { RefObject } from "react";
import { Table2, Trash2, Upload } from "lucide-react";
import { toApiError, validatePortfolio } from "../api";
import { ChoiceGroup } from "../ChoiceGroup";
import { formatPercent, normalizeTicker } from "../charts";
import { holdingsFromRows, parseCsv } from "../holdings";
import type { HoldingRow, HoldingUnits, PortfolioMode } from "../holdings";
import type { AccessResponse, SamplePortfolio } from "../types";

export function PortfolioPanel({
  access,
  portfolioSelectRef,
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
  portfolioSelectRef?: RefObject<HTMLSelectElement>;
  portfolios: SamplePortfolio[];
  portfolioKey: string;
  setPortfolioKey: (key: string) => void;
  portfolioMode: PortfolioMode;
  setPortfolioMode: (mode: PortfolioMode) => void;
  customName: string;
  setCustomName: (name: string) => void;
  customRows: HoldingRow[];
  setCustomRows: (rows: HoldingRow[]) => void;
  customUnits: HoldingUnits;
  setCustomUnits: (units: HoldingUnits) => void;
  customBenchmark: string;
  setCustomBenchmark: (ticker: string) => void;
}) {
  const selected = portfolios.find((portfolio) => portfolio.key === portfolioKey);
  const hasCash = customRows.some((row) => normalizeTicker(row.ticker) === "CASH");
  const [validation, setValidation] = useState<string[]>([]);
  const operationGenerationRef = useRef(0);
  const isShares = customUnits === "shares";

  function beginPortfolioOperation() {
    operationGenerationRef.current += 1;
    setValidation([]);
    return operationGenerationRef.current;
  }

  async function validateCustom(rows = customRows) {
    // Shares mode is validated server-side (raw share counts, no sum-to-1 rule).
    if (isShares) return;
    const requestId = beginPortfolioOperation();
    try {
      const response = await validatePortfolio(holdingsFromRows(rows));
      if (operationGenerationRef.current === requestId) setValidation(response.errors);
    } catch (exc) {
      if (operationGenerationRef.current === requestId) {
        setValidation([toApiError(exc).message]);
      }
    }
  }

  async function handleCsv(file: File | null) {
    if (!file) return;
    const uploadGeneration = beginPortfolioOperation();
    const text = await file.text();
    if (operationGenerationRef.current !== uploadGeneration) return;
    const rows = parseCsv(text);
    setCustomRows(rows);
    await validateCustom(rows);
  }

  function updateCustomRows(rows: HoldingRow[]) {
    beginPortfolioOperation();
    setCustomRows(rows);
  }

  function removeCustomRow(index: number) {
    const rows = customRows.filter((_, rowIndex) => rowIndex !== index);
    updateCustomRows(
      rows.length
        ? rows
        : [{ id: `row-${crypto.randomUUID()}`, ticker: "", weight: "" }]
    );
  }

  const admin = Boolean(access?.permissions.custom_portfolio);
  return (
    <section className="panel">
      <div className="panel-title">
        <Table2 size={16} />
        <span>Portfolio</span>
      </div>
      {admin ? (
        <ChoiceGroup<PortfolioMode>
          ariaLabel="Portfolio source"
          className="segmented"
          value={portfolioMode}
          onChange={setPortfolioMode}
          options={[
            { key: "sample", label: "Sample" },
            { key: "custom", label: "Custom" }
          ]}
        />
      ) : null}

      {portfolioMode === "sample" || !admin ? (
        <>
          <label>
            Sample book
            <select
              ref={portfolioSelectRef}
              value={portfolioKey}
              onChange={(event) => setPortfolioKey(event.target.value)}
            >
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
          <ChoiceGroup<HoldingUnits>
            ariaLabel="Holding units"
            className="segmented"
            value={customUnits}
            onChange={(units) => {
              beginPortfolioOperation();
              setCustomUnits(units);
            }}
            options={[
              { key: "weights", label: "Weights" },
              {
                key: "shares",
                label: "Shares (MTM)",
                title:
                  "Mark-to-market: enter share counts; nami marks each position to the as-of close and converts to USD"
              }
            ]}
          />
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
              <span />
            </div>
            {customRows.map((row, index) => (
              <div className="holding-row" key={row.id}>
                <input
                  value={row.ticker}
                  onChange={(event) => {
                    const next = [...customRows];
                    next[index] = { ...row, ticker: normalizeTicker(event.target.value) };
                    updateCustomRows(next);
                  }}
                  placeholder="Ticker"
                  aria-label={`Ticker for holding ${index + 1}`}
                />
                <input
                  value={row.weight}
                  onChange={(event) => {
                    const next = [...customRows];
                    next[index] = { ...row, weight: event.target.value };
                    updateCustomRows(next);
                  }}
                  placeholder={isShares ? "100" : "0.25"}
                  inputMode={isShares ? "numeric" : "decimal"}
                  aria-label={`${isShares ? "Shares" : "Weight"} for holding ${index + 1}`}
                />
                <button
                  type="button"
                  className="holding-remove-button"
                  aria-label={`Remove ${
                    normalizeTicker(row.ticker)
                      ? `${normalizeTicker(row.ticker)} holding`
                      : `holding ${index + 1}`
                  }`}
                  onClick={() => removeCustomRow(index)}
                >
                  <Trash2 size={16} aria-hidden="true" />
                </button>
              </div>
            ))}
          </div>
          <div className="button-row">
            <button
              className="ghost-button"
              onClick={() =>
                updateCustomRows([
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
                updateCustomRows([
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

export interface TopHoldingsSummary {
  rows: Array<{ ticker: string; weight: number }>;
  coverage: number;
  remaining: number;
}

export function summarizeTopHoldings(
  holdings: Record<string, number>,
  limit: number
): TopHoldingsSummary {
  const rowLimit = Math.max(0, Math.floor(limit));
  const entries = Object.entries(holdings)
    .map(([ticker, weight]) => ({ ticker, weight: Number(weight) }))
    .sort((left, right) => {
      const byWeight = right.weight - left.weight;
      if (byWeight !== 0) return byWeight;
      if (left.ticker < right.ticker) return -1;
      if (left.ticker > right.ticker) return 1;
      return 0;
    });
  const rows = entries.slice(0, rowLimit);

  return {
    rows,
    coverage: rows.reduce((total, row) => total + row.weight, 0),
    remaining: Math.max(0, entries.length - rows.length)
  };
}

function MiniHoldings({ holdings }: { holdings: Record<string, number> }) {
  const summary = summarizeTopHoldings(holdings, 8);
  if (!summary.rows.length) {
    return <p className="muted mini-holdings-empty">No holdings available.</p>;
  }

  return (
    <div className="mini-holdings">
      <p className="mini-holdings-summary">
        Top {summary.rows.length} · {formatPercent(summary.coverage, 1)} of book
      </p>
      <div className="mini-holdings-list">
        {summary.rows.map((row) => (
          <span key={row.ticker}>
            {row.ticker} {formatPercent(row.weight, 1)}
          </span>
        ))}
        {summary.remaining ? <span>+{summary.remaining} more</span> : null}
      </div>
    </div>
  );
}
