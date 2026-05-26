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
              <strong>Naive</strong>
              <span className="guide-formula">(&#x2211; w&#x1d62;&#x3b2;&#x1d62;,f) &middot; shock[f]</span>
              <p>Best for: Quick intuition, independent factors</p>
            </div>

            <div className="guide-method">
              <strong>Conditional (full)</strong>
              <span className="guide-formula">Full Shapley, all F factors</span>
              <p>Best for: Axiom-compliant, correlated equities</p>
              <p className="guide-note">Can credit factors LLM didn't shock</p>
            </div>

            <div className="guide-method">
              <strong>Explicit-only</strong>
              <span className="guide-formula">Shapley, LLM-shocked factors only</span>
              <p>Best for: "What did the model actually name?"</p>
              <p className="guide-note">Sum may be less than factor-driven P&L</p>
            </div>

            <div className="guide-method">
              <strong>Grouped</strong>
              <span className="guide-formula">Shapley over 4 groups, redistributed</span>
              <p>Best for: Collapsing within-group leakage</p>
              <p className="guide-note">Market / Sector / Style / Macro grouping</p>
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
