import { useRef, useState } from "react";
import { Maximize2, Minimize2 } from "lucide-react";
import { nextEnabledMethod } from "../attributionNav";
import {
  buildWaterfallData,
  factorReasoningRows,
  formatPercent,
  hasCorrelationCrossCredit
} from "../charts";
import { TableScroll } from "../TableScroll";
import { useFullscreen } from "../useFullscreen";
import type { AttributionOption } from "./AttributionControl";
import { WaterfallChart } from "./WaterfallChart";
import type { AttributionMethod, FactorMetadataMap, ScenarioResult } from "../types";

/** Admin audit views (Phase 31i): the production surface shows ONE
 * methodology (explicit conditional Shapley); the alternative credit-splitting
 * rules live here for audit and comparison. Same total, different splits —
 * none of these may ever drive the headline (full-conditional especially:
 * it assigns P&L to factors the scenario never shocked). */
export function MethodologyDiagnostics({
  result,
  factorMeta
}: {
  result: ScenarioResult;
  factorMeta: FactorMetadataMap;
}) {
  const [method, setMethod] = useState<AttributionMethod>("naive");
  const cardRef = useRef<HTMLDivElement>(null);
  const fullscreen = useFullscreen(cardRef);

  const options: AttributionOption[] = [
    {
      method: "naive",
      label: "Naive algebra",
      title: "Direct algebraic attribution. Useful for audit/debug; assumes factor independence.",
      disabled: false
    },
    {
      method: "conditional",
      label: "Full conditional",
      title:
        "Correlation-credit diagnostic under the full historical joint distribution. Non-causal; can credit unshocked factors.",
      disabled: !result.portfolio_pnl.by_factor_conditional_shapley
    },
    {
      method: "conditional_grouped",
      label: "Grouped (full conditional)",
      title:
        "Group totals under the FULL conditional distribution — includes correlation credit; kept for comparison with the production rollup.",
      disabled: !result.portfolio_pnl.by_factor_conditional_shapley_grouped
    }
  ];

  function move(direction: 1 | -1) {
    setMethod(nextEnabledMethod(options, method, direction));
  }

  const waterfall = buildWaterfallData(result, method, factorMeta);
  const rows = factorReasoningRows(result, method, factorMeta);

  return (
    <div className="result-card diagnostics-card" ref={cardRef}>
      <div className="card-heading">
        <div>
          <p className="eyebrow">Audit</p>
          <h3>Methodology diagnostics</h3>
          <p className="muted card-subtitle">
            Audit views — same total, different credit-splitting rules.
          </p>
        </div>
        <div className="card-heading-actions">
          <div
            className="segmented"
            role="radiogroup"
            aria-label="Diagnostic attribution method"
            onKeyDown={(event) => {
              if (event.key === "ArrowRight" || event.key === "ArrowDown") {
                event.preventDefault();
                move(1);
              } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
                event.preventDefault();
                move(-1);
              }
            }}
          >
            {options.map((option) => (
              <button
                key={option.method}
                role="radio"
                aria-checked={method === option.method}
                tabIndex={method === option.method ? 0 : -1}
                className={method === option.method ? "active" : ""}
                onClick={() => setMethod(option.method)}
                disabled={option.disabled}
                title={option.title}
              >
                {option.label}
              </button>
            ))}
          </div>
          {fullscreen.supported ? (
            <button
              type="button"
              className="methodology-btn"
              onClick={fullscreen.toggle}
              aria-label={fullscreen.isFullscreen ? "Exit full screen" : "View full screen"}
              title={fullscreen.isFullscreen ? "Exit full screen" : "View full screen"}
            >
              {fullscreen.isFullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
            </button>
          ) : null}
        </div>
      </div>
      {method === "conditional" || method === "conditional_grouped" ? (
        <p className="muted">
          Correlation credit, non-causal. Unshocked factors can receive positive or negative
          P&amp;L through historical co-movement; do not read those bars as explicit scenario
          shocks.
        </p>
      ) : (
        <p className="muted">
          Direct algebraic attribution. Useful for audit/debug; assumes factor independence —
          collinear factors show large offsetting bars.
        </p>
      )}
      <WaterfallChart
        waterfall={waterfall}
        showDollars={false}
        chartHeight={
          fullscreen.isFullscreen
            ? Math.max(420, (typeof window !== "undefined" ? window.innerHeight : 800) - 260)
            : 360
        }
        isPhone={false}
      />
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Factor</th>
              <th className="num">Shock</th>
              <th className="num">P&L contrib</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.factor} className={row.isCorrelationCredit ? "diagnostic-row" : ""}>
                <td>{row.factorLabel}</td>
                <td className="num">{formatPercent(row.shockApplied)}</td>
                <td className="num">{formatPercent(row.contribution)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
      {hasCorrelationCrossCredit(method) ? (
        <p className="hint">
          Rows without an explicit shock show{" "}
          <em>Correlation credit; no explicit shock</em> in the production table.
        </p>
      ) : null}
    </div>
  );
}
