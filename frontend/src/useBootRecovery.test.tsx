import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useBootRecovery } from "./useBootRecovery";

function RecoveryHarness({ enabled, onRecover }: { enabled: boolean; onRecover: () => void }) {
  useBootRecovery({ enabled, onRecover });
  return null;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useBootRecovery", () => {
  it("recovers on reconnect only while enabled and removes listeners on cleanup", () => {
    const onRecover = vi.fn();
    const view = render(<RecoveryHarness enabled={false} onRecover={onRecover} />);

    window.dispatchEvent(new Event("online"));
    expect(onRecover).not.toHaveBeenCalled();

    view.rerender(<RecoveryHarness enabled onRecover={onRecover} />);
    window.dispatchEvent(new Event("online"));
    expect(onRecover).toHaveBeenCalledTimes(1);

    view.unmount();
    window.dispatchEvent(new Event("online"));
    expect(onRecover).toHaveBeenCalledTimes(1);
  });

  it("recovers when a failed boot tab becomes visible and ignores hidden tabs", () => {
    let visibility: DocumentVisibilityState = "hidden";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
    const onRecover = vi.fn();
    render(<RecoveryHarness enabled onRecover={onRecover} />);

    document.dispatchEvent(new Event("visibilitychange"));
    expect(onRecover).not.toHaveBeenCalled();

    visibility = "visible";
    document.dispatchEvent(new Event("visibilitychange"));
    expect(onRecover).toHaveBeenCalledTimes(1);
  });

  it("coalesces reconnect signals and a successful boot disables later recovery", () => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    const onRecover = vi.fn();
    const view = render(<RecoveryHarness enabled onRecover={onRecover} />);

    window.dispatchEvent(new Event("online"));
    document.dispatchEvent(new Event("visibilitychange"));
    expect(onRecover).toHaveBeenCalledTimes(1);

    view.rerender(<RecoveryHarness enabled={false} onRecover={onRecover} />);
    window.dispatchEvent(new Event("online"));
    document.dispatchEvent(new Event("visibilitychange"));
    expect(onRecover).toHaveBeenCalledTimes(1);
  });
});
