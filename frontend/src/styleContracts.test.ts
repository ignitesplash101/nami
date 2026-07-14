import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const styles = readFileSync("src/styles.css", "utf8");

describe("interactive target CSS contracts", () => {
  it("loads the authored stylesheet", () => {
    expect(styles).toContain(".saved-open");
  });

  it("keeps every saved-open cascade declaration at least 44px tall", () => {
    const heights = Array.from(
      styles.matchAll(/\.saved-open\s*\{[^}]*min-height:\s*(\d+)px/g),
      (match) => Number(match[1])
    );

    expect(heights.length).toBeGreaterThanOrEqual(2);
    expect(heights.every((height) => height >= 44)).toBe(true);
  });

  it("keeps InfoTip compact in layout while extending its clickable box to 44px", () => {
    const buttonRule = styles.match(/\.infotip-btn\s*\{([^}]*)\}/)?.[1] ?? "";
    const hitRule = styles.match(/\.infotip-btn::before\s*\{([^}]*)\}/)?.[1] ?? "";

    expect(buttonRule).toMatch(/position:\s*relative/);
    expect(buttonRule).toMatch(/width:\s*24px/);
    expect(buttonRule).toMatch(/height:\s*24px/);
    expect(buttonRule).not.toMatch(/(?:min-width|min-height):\s*44px/);
    expect(hitRule).toMatch(/content:\s*""/);
    expect(hitRule).toMatch(/position:\s*absolute/);
    expect(hitRule).toMatch(/inset:\s*-10px/);
  });
});
