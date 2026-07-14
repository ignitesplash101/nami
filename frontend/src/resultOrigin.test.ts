import { describe, expect, it } from "vitest";
import { canEditAndRerun } from "./resultOrigin";

describe("result origin", () => {
  it("allows Edit & re-run only for saved or permalinked results", () => {
    expect(canEditAndRerun("saved")).toBe(true);
    expect(canEditAndRerun("live")).toBe(false);
    expect(canEditAndRerun(null)).toBe(false);
  });
});
