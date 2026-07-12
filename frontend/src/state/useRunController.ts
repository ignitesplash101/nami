import { useRef, useState } from "react";
import { decomposeScenarioStream, runScenarioStream } from "../api";
import type { RunScenarioPayload } from "../api";
import { createRunLifecycle } from "../runLifecycle";
import type { ScenarioResult, ScenarioRunResponse, SsePipelineStage } from "../types";

/** The run + decompose stream machinery. Lives ABOVE any tab/panel structure
 * (nothing that owns a stream may ever unmount) and keeps the two lifecycles
 * separate: cancelling/superseding a run must not abort an in-flight
 * decomposition and vice versa. All late frames/results/finallys are dropped
 * by the isCurrent sequence guards. */
export function useRunController(opts: {
  // null = not ready to run (access still booting).
  buildRunPayload: () => RunScenarioPayload | null;
  onRunResult: (response: ScenarioRunResponse) => void;
  getDecomposeSource: () => ScenarioResult | null;
  onDecomposeResult: (response: ScenarioRunResponse) => void;
  onError: (exc: unknown, action: "run" | "decompose") => void;
  clearError: () => void;
}) {
  const [isRunning, setIsRunning] = useState(false);
  const [isDecomposing, setIsDecomposing] = useState(false);
  const [decomposeProgress, setDecomposeProgress] = useState<{ done: number; total: number } | null>(
    null
  );
  const [currentStage, setCurrentStage] = useState<SsePipelineStage | null>(null);
  const [stageStatus, setStageStatus] = useState<"start" | "done" | null>(null);
  const [completedStages, setCompletedStages] = useState<Set<SsePipelineStage>>(new Set());
  const [cacheHit, setCacheHit] = useState(false);
  // Separate lifecycles: cancelling/superseding a run must not abort an
  // in-flight decomposition and vice versa.
  const runLifecycle = useRef(createRunLifecycle()).current;
  const decomposeLifecycle = useRef(createRunLifecycle()).current;
  // Bumped only when a RUN completes (not adjustments or saved-scenario opens):
  // App's effect scrolls the fresh results into view.
  const [runSerial, setRunSerial] = useState(0);

  async function handleRun() {
    const payload = opts.buildRunPayload();
    if (payload == null) return;
    // begin() aborts any in-flight run and invalidates its sequence — its late
    // frames/result/finally are dropped by the isCurrent guards below.
    const handle = runLifecycle.begin();
    opts.clearError();
    setIsRunning(true);
    setCurrentStage(null);
    setStageStatus(null);
    setCompletedStages(new Set());
    setCacheHit(false);
    try {
      const response = await runScenarioStream(
        payload,
        (event) => {
          if (!runLifecycle.isCurrent(handle.seq)) return;
          if (event.stage === "cache_hit") {
            setCacheHit(true);
            return;
          }
          if (event.stage === "done" || event.stage === "error") {
            return;
          }
          setCurrentStage(event.stage);
          setStageStatus(event.status ?? null);
          if (event.status === "done") {
            setCompletedStages((prev) => new Set(prev).add(event.stage));
          }
        },
        { signal: handle.signal }
      );
      if (!runLifecycle.isCurrent(handle.seq)) return;
      opts.onRunResult(response);
      setRunSerial((serial) => serial + 1);
    } catch (exc) {
      if (!runLifecycle.isCurrent(handle.seq)) return;
      opts.onError(exc, "run");
    } finally {
      if (runLifecycle.isCurrent(handle.seq)) {
        setIsRunning(false);
      }
    }
  }

  function handleCancelRun() {
    runLifecycle.cancel();
  }

  async function handleDecompose() {
    const source = opts.getDecomposeSource();
    if (!source) return;
    const handle = decomposeLifecycle.begin();
    opts.clearError();
    setIsDecomposing(true);
    setDecomposeProgress(null);
    try {
      const response = await decomposeScenarioStream(
        source,
        (done, total) => {
          if (decomposeLifecycle.isCurrent(handle.seq)) setDecomposeProgress({ done, total });
        },
        { signal: handle.signal }
      );
      if (!decomposeLifecycle.isCurrent(handle.seq)) return;
      opts.onDecomposeResult(response);
    } catch (exc) {
      if (!decomposeLifecycle.isCurrent(handle.seq)) return;
      opts.onError(exc, "decompose");
    } finally {
      if (decomposeLifecycle.isCurrent(handle.seq)) {
        setIsDecomposing(false);
        setDecomposeProgress(null);
      }
    }
  }

  function handleCancelDecompose() {
    decomposeLifecycle.cancel();
  }

  return {
    isRunning,
    isDecomposing,
    decomposeProgress,
    currentStage,
    stageStatus,
    completedStages,
    cacheHit,
    runSerial,
    handleRun,
    handleCancelRun,
    handleDecompose,
    handleCancelDecompose
  };
}
