import { describe, expect, it } from "vitest";
import { nextEnabledMethod } from "./attributionNav";
import type { AttributionOption } from "./attributionNav";

const allEnabled: AttributionOption[] = [
  { method: "naive", disabled: false },
  { method: "conditional", disabled: false },
  { method: "conditional_explicit", disabled: false },
  { method: "conditional_grouped", disabled: false }
];

describe("nextEnabledMethod", () => {
  it("moves forward to the next option", () => {
    expect(nextEnabledMethod(allEnabled, "naive", 1)).toBe("conditional");
  });

  it("wraps forward from the last option to the first", () => {
    expect(nextEnabledMethod(allEnabled, "conditional_grouped", 1)).toBe("naive");
  });

  it("wraps backward from the first option to the last", () => {
    expect(nextEnabledMethod(allEnabled, "naive", -1)).toBe("conditional_grouped");
  });

  it("skips disabled options when moving forward", () => {
    const opts: AttributionOption[] = [
      { method: "naive", disabled: false },
      { method: "conditional", disabled: true },
      { method: "conditional_explicit", disabled: false },
      { method: "conditional_grouped", disabled: true }
    ];
    expect(nextEnabledMethod(opts, "naive", 1)).toBe("conditional_explicit");
    // From the only other enabled option, forward wraps back to naive.
    expect(nextEnabledMethod(opts, "conditional_explicit", 1)).toBe("naive");
  });

  it("returns the current method when it is not among the enabled options", () => {
    const opts: AttributionOption[] = [
      { method: "naive", disabled: false },
      { method: "conditional", disabled: true }
    ];
    expect(nextEnabledMethod(opts, "conditional", 1)).toBe("conditional");
  });

  it("returns the current method when nothing is enabled", () => {
    const opts: AttributionOption[] = [{ method: "naive", disabled: true }];
    expect(nextEnabledMethod(opts, "naive", 1)).toBe("naive");
  });
});
