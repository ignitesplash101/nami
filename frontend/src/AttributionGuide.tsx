import { useState } from "react";
import { HelpCircle, ChevronDown, ChevronRight, ArrowRight } from "lucide-react";

export function AttributionGuide({
  onOpenMethodology,
}: {
  onOpenMethodology: (section: string) => void;
}) {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="attribution-guide">
      <button
        className="guide-toggle"
        onClick={() => setIsExpanded(!isExpanded)}
        aria-expanded={isExpanded}
      >
        <HelpCircle size={14} />
        <span>Which method should I use?</span>
        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>

      {isExpanded ? (
        <div className="guide-body">
          <div className="guide-methods">
            <div className="guide-method">
              <strong>Scenario shocks</strong>
              <span className="guide-formula">Production risk view</span>
              <p>Best for: PM/risk-manager readout</p>
              <p className="guide-note">Only factors explicitly shocked by the scenario</p>
            </div>

            <div className="guide-method">
              <strong>Group totals</strong>
              <span className="guide-formula">Market / sector / style / macro</span>
              <p>Best for: Risk committee summaries</p>
              <p className="guide-note">Shows true group totals; factor detail stays below</p>
            </div>

            <div className="guide-method">
              <strong>Naive algebra</strong>
              <span className="guide-formula">Audit/debug</span>
              <p>Best for: Direct formula checks</p>
              <p className="guide-note">Assumes factor independence</p>
            </div>

            <div className="guide-method">
              <strong>Full conditional diagnostic</strong>
              <span className="guide-formula">Correlation credit, non-causal</span>
              <p>Best for: Quant diagnostics</p>
              <p className="guide-note">Can credit unshocked factors</p>
            </div>
          </div>

          <button
            className="guide-deeplink"
            onClick={() => onOpenMethodology("factor-attribution")}
          >
            Read full methodology <ArrowRight size={13} />
          </button>
        </div>
      ) : null}
    </div>
  );
}
