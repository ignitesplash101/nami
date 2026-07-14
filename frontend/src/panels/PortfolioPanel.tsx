import { useState } from "react";
import type { RefObject } from "react";
import { Table2, Upload } from "lucide-react";
import { toApiError, validatePortfolio } from "../api";
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
