import { formatEvidence } from "../format";
import { factorDisplayName } from "../factors";
import { ChoiceGroup } from "../ChoiceGroup";
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
  setAttributionMethod
}: {
  options: AttributionOption[];
  attributionMethod: AttributionMethod;
  setAttributionMethod: (method: AttributionMethod) => void;
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
      <ChoiceGroup<AttributionMethod>
        ariaLabel="Advanced attribution diagnostics"
        className="segmented"
        value={attributionMethod}
        onChange={setAttributionMethod}
        options={options.map((option) => ({
          key: option.method,
          label: option.label,
          disabled: option.disabled,
          title: option.title
        }))}
      />
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
  // Warnings open by default; informational notes (typically correlation-credit
  // audits of a method the main chart does not show) wait behind one summary
  // line instead of pushing the chart below the fold.
  const warnings = diagnostics.filter((diagnostic) => diagnostic.severity === "warning").length;
  const notes = diagnostics.length - warnings;
  const summary = [
    warnings ? `${warnings} warning${warnings === 1 ? "" : "s"}` : null,
    notes ? `${notes} informational note${notes === 1 ? "" : "s"}` : null
  ]
    .filter(Boolean)
    .join(" and ");
  return (
    <details
      className={`risk-diagnostics${warnings ? " has-warning" : ""}`}
      role="note"
      aria-label="Risk diagnostics"
      open={warnings > 0}
    >
      <summary>
        <span className="risk-diagnostics-title">Model diagnostics</span>
        <span className="risk-diagnostics-count">{summary}</span>
      </summary>
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
    </details>
  );
}
