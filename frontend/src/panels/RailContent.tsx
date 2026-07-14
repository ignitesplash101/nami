import type { RefObject } from "react";
import { Activity } from "lucide-react";
import { AccessPanel } from "./AccessPanel";
import { PortfolioPanel } from "./PortfolioPanel";
import type { HoldingRow, HoldingUnits, PortfolioMode } from "../holdings";
import type { AccessResponse, SamplePortfolio } from "../types";

/** The rail's shared content: brand block + access + portfolio setup. Rendered
 * exactly once — inline <aside> on desktop OR inside RailDrawer on compact —
 * so the panels' local state never forks between two mounted copies. */
export function RailContent({
  access,
  onAccessChange,
  passcodeInputRef,
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
  setCustomBenchmark,
  onOpenOperations
}: {
  access: AccessResponse | null;
  onAccessChange: (access: AccessResponse, opts?: { intentional?: boolean }) => void;
  passcodeInputRef?: RefObject<HTMLInputElement>;
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
  onOpenOperations?: () => void;
}) {
  return (
    <>
      <div className="brand-block">
        <span className="brand-glyph" aria-hidden="true">波</span>
        <div className="brand-kicker">nami</div>
        <div className="brand-title">Scenario Explorer</div>
        <p>Equity portfolio shocks, analog-grounded narratives, factor attribution.</p>
        <div className="brand-crest" aria-hidden="true" />
      </div>
      <AccessPanel access={access} onAccessChange={onAccessChange} passcodeInputRef={passcodeInputRef} />
      {access?.access_mode === "admin" && onOpenOperations ? (
        <button
          type="button"
          className="ghost-button rail-ops-button"
          onClick={onOpenOperations}
          aria-label="Open operations console"
        >
          <Activity size={15} /> Operations console
        </button>
      ) : null}
      <PortfolioPanel
        access={access}
        portfolioSelectRef={portfolioSelectRef}
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
}
