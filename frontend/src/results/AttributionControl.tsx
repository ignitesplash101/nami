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
