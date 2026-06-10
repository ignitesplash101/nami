import { describe, expect, it } from "vitest";
import { createRunLifecycle } from "./runLifecycle";

describe("createRunLifecycle", () => {
  it("aborts the prior handle's signal when a new run begins", () => {
    const lifecycle = createRunLifecycle();
    const first = lifecycle.begin();
    expect(first.signal.aborted).toBe(false);

    const second = lifecycle.begin();
    expect(first.signal.aborted).toBe(true);
    expect(second.signal.aborted).toBe(false);
  });

  it("invalidates stale sequence numbers", () => {
    const lifecycle = createRunLifecycle();
    const first = lifecycle.begin();
    expect(lifecycle.isCurrent(first.seq)).toBe(true);

    const second = lifecycle.begin();
    expect(lifecycle.isCurrent(first.seq)).toBe(false);
    expect(lifecycle.isCurrent(second.seq)).toBe(true);
  });

  it("cancel aborts without invalidating the current sequence", () => {
    const lifecycle = createRunLifecycle();
    const handle = lifecycle.begin();
    lifecycle.cancel();
    expect(handle.signal.aborted).toBe(true);
    // The cancelled run's own catch/finally must still apply.
    expect(lifecycle.isCurrent(handle.seq)).toBe(true);
  });
});
