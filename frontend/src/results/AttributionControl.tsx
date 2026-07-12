import { formatEvidence } from "../format";
import { factorDisplayName } from "../factors";
import type {
  AttributionMethod,
  FactorMetadataMap,
  RiskDiagnostic as RiskDiagnosticRecord
} from "../types";

export interface AttributionOption {
  method: AttributionMethod;
  label: string;
  title: string;
  disabled: boolean;
}

export function AdvancedAttributionDiagnostics({
  options,
  attributionMethod,
  setAttributionMethod,
  moveAttribution
}: {
  options: AttributionOption[];
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

export function RiskDiagnostics({
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
