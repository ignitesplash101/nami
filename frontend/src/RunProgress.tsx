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
}

export function RunProgress({
  currentStage,
  stageStatus,
  completedStages,
  cacheHit
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
            <li key={stage} className={className}>
              <span className="dot" />
              <span className="label">{STAGE_LABELS[stage]}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
