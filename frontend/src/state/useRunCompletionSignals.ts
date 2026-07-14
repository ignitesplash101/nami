import { useEffect, useRef } from "react";
import type { ToastInput } from "../toast";

export interface RunCompletionSignals {
  /** Run-completion counter from useRunController. It bumps ONLY on a
   * successfully completed run — never on failures, cancellations, adjustments,
   * or decompositions — so every bump here is a fresh result worth surfacing.
   * (No extra success tracking is needed: the serial already guarantees it.) */
  runSerial: number;
  isScenarioArea: boolean;
  /** Pre-formatted headline P&L for the completion toast message. */
  headlinePnl: string;
  pushToast: (toast: ToastInput) => void;
  goToScenarioArea: () => void;
  scrollToResults: () => void;
}

/** Surfaces a completed run so it is never a silent no-op:
 *  - in the Scenario area → scroll the fresh results into view;
 *  - elsewhere → a VISUAL-ONLY completion toast (App owns the single polite
 *    live region for run lifecycle, so the toast must not re-announce it) plus a
 *    scroll deferred until the user returns to the Scenario area.
 *
 * The refs make each runSerial idempotent: React re-renders / dependency churn
 * must not replay a toast or a scroll. */
export function useRunCompletionSignals({
  runSerial,
  isScenarioArea,
  headlinePnl,
  pushToast,
  goToScenarioArea,
  scrollToResults
}: RunCompletionSignals): void {
  const lastHandledRunSerialRef = useRef(0);
  const pendingScrollSerialRef = useRef<number | null>(null);

  useEffect(() => {
    // Serial 0 is the initial mount (no run yet); a repeated serial is a plain
    // re-render — neither is a fresh completion to surface.
    if (runSerial === 0 || runSerial === lastHandledRunSerialRef.current) return;
    lastHandledRunSerialRef.current = runSerial;
    if (isScenarioArea) {
      scrollToResults();
    } else {
      pendingScrollSerialRef.current = runSerial;
      pushToast({
        variant: "success",
        silent: true,
        message: `Scenario complete — ${headlinePnl}`,
        actionLabel: "View",
        onAction: goToScenarioArea
      });
    }
    // Keyed on runSerial only: the callbacks/labels are read fresh from the
    // render that bumped the serial, and the ref guard makes handling idempotent
    // regardless of the other inputs churning between runs.
  }, [runSerial]);

  useEffect(() => {
    if (!isScenarioArea || pendingScrollSerialRef.current === null) return;
    pendingScrollSerialRef.current = null;
    // The Scenario tab panel just unhid — wait one frame so its layout exists
    // before scrolling the freshly revealed results into view.
    const frame = requestAnimationFrame(() => scrollToResults());
    return () => cancelAnimationFrame(frame);
  }, [isScenarioArea]);
}
