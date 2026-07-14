import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRunCompletionSignals } from "./useRunCompletionSignals";
import type { RunCompletionSignals } from "./useRunCompletionSignals";

function harness(overrides: Partial<RunCompletionSignals> = {}) {
  const pushToast = vi.fn();
  const goToScenarioArea = vi.fn();
  const scrollToResults = vi.fn();
  const initialProps: RunCompletionSignals = {
    runSerial: 0,
    isScenarioArea: true,
    headlinePnl: "-1.00%",
    pushToast,
    goToScenarioArea,
    scrollToResults,
    ...overrides
  };
  const view = renderHook((props: RunCompletionSignals) => useRunCompletionSignals(props), {
    initialProps
  });
  return { view, pushToast, goToScenarioArea, scrollToResults, initialProps };
}

describe("useRunCompletionSignals", () => {
  // The deferred scroll runs on requestAnimationFrame; fire it synchronously so
  // the effect's scroll is observable without a real frame.
  beforeEach(() => {
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      cb(0);
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", () => {});
  });
  afterEach(() => vi.unstubAllGlobals());

  it("does nothing on serial 0 / initial mount", () => {
    const { scrollToResults, pushToast } = harness({ runSerial: 0 });
    expect(scrollToResults).not.toHaveBeenCalled();
    expect(pushToast).not.toHaveBeenCalled();
  });

  it("scrolls exactly once when a run lands while in the scenario area", () => {
    const { view, scrollToResults, pushToast, initialProps } = harness({ isScenarioArea: true });
    act(() => view.rerender({ ...initialProps, runSerial: 1 }));
    expect(scrollToResults).toHaveBeenCalledTimes(1);
    expect(pushToast).not.toHaveBeenCalled();
  });

  it("pushes a silent completion toast (no scroll) when out of the scenario area", () => {
    const { view, scrollToResults, pushToast, goToScenarioArea, initialProps } = harness({
      isScenarioArea: false,
      headlinePnl: "-12.34%"
    });
    act(() => view.rerender({ ...initialProps, runSerial: 1 }));
    expect(scrollToResults).not.toHaveBeenCalled();
    expect(pushToast).toHaveBeenCalledTimes(1);
    const toast = pushToast.mock.calls[0][0];
    expect(toast).toMatchObject({
      variant: "success",
      silent: true,
      message: "Scenario complete — -12.34%",
      actionLabel: "View"
    });
    toast.onAction();
    expect(goToScenarioArea).toHaveBeenCalledTimes(1);
  });

  it("defers the scroll until the user returns, firing it exactly once", () => {
    const { view, scrollToResults, initialProps } = harness({ isScenarioArea: false });
    act(() => view.rerender({ ...initialProps, runSerial: 1 }));
    expect(scrollToResults).not.toHaveBeenCalled();

    act(() => view.rerender({ ...initialProps, runSerial: 1, isScenarioArea: true }));
    expect(scrollToResults).toHaveBeenCalledTimes(1);

    // Further in-area re-renders must not replay the deferred scroll.
    act(() =>
      view.rerender({ ...initialProps, runSerial: 1, isScenarioArea: true, headlinePnl: "x" })
    );
    expect(scrollToResults).toHaveBeenCalledTimes(1);
  });

  it("handles each serial exactly once across duplicate re-renders", () => {
    const { view, scrollToResults, pushToast, initialProps } = harness({ isScenarioArea: true });
    act(() => view.rerender({ ...initialProps, runSerial: 1 }));
    act(() => view.rerender({ ...initialProps, runSerial: 1 }));
    expect(scrollToResults).toHaveBeenCalledTimes(1);
    expect(pushToast).not.toHaveBeenCalled();
  });
});
