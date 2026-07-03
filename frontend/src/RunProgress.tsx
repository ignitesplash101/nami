import type { SsePipelineStage } from "./types";

const STAGE_LABELS: Record<Exclude<SsePipelineStage, "done" | "error" | "cache_hit">, string> = {
  cache_check: "Checking cache",
  market: "Fetching market data",
  analogs: "Selecting historical analogs",
  envelope: "Computing analog envelope",
  narrative: "Grounding narrative (Google Search)",
  betas: "Estimating factor betas",
  attribution: "Computing attribution"
};

/** Human label for a pipeline stage; used by the stepper AND the App-level
 * aria-live announcer so screen readers hear the same text the stepper shows. */
export function stageLabel(stage: SsePipelineStage): string | null {
  return stage in STAGE_LABELS ? STAGE_LABELS[stage as keyof typeof STAGE_LABELS] : null;
}

const STAGE_ORDER: (keyof typeof STAGE_LABELS)[] = [
  "cache_check",
  "market",
  "analogs",
  "envelope",
  "narrative",
  "betas",
  "attribution"
];

export interface RunProgressProps {
  currentStage: SsePipelineStage | null;
  stageStatus: "start" | "done" | null;
  completedStages: Set<SsePipelineStage>;
  cacheHit: boolean;
  onCancel?: () => void;
}

export function RunProgress({
  currentStage,
  stageStatus,
  completedStages,
  cacheHit,
  onCancel
}: RunProgressProps) {
  if (cacheHit) {
    return (
      <div className="run-progress cache-hit">
        <span className="badge">Cache hit</span>
        <p className="muted">Loaded a previously computed result for this scenario.</p>
      </div>
    );
  }
  return (
    <div className="run-progress">
      <ol>
        {STAGE_ORDER.map((stage) => {
          const isActive = currentStage === stage && stageStatus === "start";
          const isDone = completedStages.has(stage);
          const className = isActive ? "active" : isDone ? "done" : "pending";
          return (
            <li key={stage} className={className} aria-current={isActive ? "step" : undefined}>
              <span className="dot" />
              <span className="label">{STAGE_LABELS[stage]}</span>
            </li>
          );
        })}
      </ol>
      {onCancel ? (
        <div className="run-cancel-row">
          <button type="button" className="ghost-button" onClick={onCancel}>
            Cancel run
          </button>
          <span className="muted">
            Cancelling stops this view; the server may still finish and warm the cache, so
            retrying can be instant.
          </span>
        </div>
      ) : null}
    </div>
  );
}
