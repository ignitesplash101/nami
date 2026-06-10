import { afterEach, describe, expect, it, vi } from "vitest";
import { csvEscape, csvFilename, downloadCsv, toCsv } from "./csv";

afterEach(() => vi.unstubAllGlobals());

describe("csvEscape", () => {
  it("escapes commas, quotes, and newlines", () => {
    expect(csvEscape('a "b", c')).toBe('"a ""b"", c"');
    expect(csvEscape("line1\nline2")).toBe('"line1\nline2"');
    expect(csvEscape("plain")).toBe("plain");
  });
});

describe("toCsv", () => {
  it("joins rows with CRLF and renders null/undefined as empty", () => {
    const csv = toCsv(["h1", "h2"], [["x,y", 'q"r'], [1, null]]);
    expect(csv).toBe('h1,h2\r\n"x,y","q""r"\r\n1,');
  });

  it("guards text cells against Excel formula injection", () => {
    const csv = toCsv(["reasoning"], [["=SUM(A1)"], ["@cmd"], ["+positive spin"], ["-led selloff"]]);
    expect(csv).toContain("'=SUM(A1)");
    expect(csv).toContain("'@cmd");
    expect(csv).toContain("'+positive spin");
    expect(csv).toContain("'-led selloff");
  });

  it("keeps number-typed cells raw so decimals stay machine-parseable", () => {
    const csv = toCsv(["shock"], [[-0.0612]]);
    expect(csv).toBe("shock\r\n-0.0612");
  });
});

describe("csvFilename", () => {
  it("builds semantic slugged filenames", () => {
    expect(
      csvFilename(
        "us_tech_growth",
        "China tariff escalation hits semis",
        "2026-06-10",
        "factor-shocks"
      )
    ).toBe("nami_us-tech-growth_china-tariff-escalation-hits-semis_2026-06-10_factor-shocks.csv");
  });
});

describe("downloadCsv", () => {
  it("creates and revokes an object URL around the anchor click", () => {
    const createObjectURL = vi.fn(() => "blob:x");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    downloadCsv("test.csv", ["h"], [["v"]]);

    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:x");
    click.mockRestore();
  });
});
