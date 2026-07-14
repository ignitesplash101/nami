import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const styles = readFileSync("src/styles.css", "utf8");
const app = readFileSync("src/App.tsx", "utf8");
const scenarioPanel = readFileSync("src/panels/ScenarioPanel.tsx", "utf8");

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

describe("responsive composition contracts", () => {
  it("groups the compact setup trigger with the workbench title", () => {
    expect(app).toContain('className="topbar-nav-cluster"');
    expect(styles).toMatch(/\.topbar-nav-cluster\s*\{[^}]*display:\s*flex/s);
  });

  it("never presents the setup drawer in the same desktop render as the inline rail", () => {
    expect(app).toContain("isOpen={isMobileOrTablet && railDrawer.isOpen}");
  });

  it("gives the phone scenario strip an edge affordance and scroll snapping", () => {
    expect(scenarioPanel).toContain('className="scenario-chips-wrap"');
    expect(styles).toMatch(/\.scenario-chips-wrap::after\s*\{/);
    expect(styles).toMatch(/\.scenario-chips\s*\{[^}]*scroll-snap-type:\s*x\s+proximity/s);
    expect(styles).toMatch(/\.scenario-chips\s+\.chip\s*\{[^}]*scroll-snap-align:\s*start/s);
  });

  it("uses an approximately 2:3 book-profile layout from 1600px", () => {
    expect(styles).toMatch(
      /@media\s*\(min-width:\s*1600px\)[\s\S]*?\.book-profile-layout\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*2fr\)\s+minmax\(0,\s*3fr\)/
    );
  });

  it("places the phone toolbar alignment override after the desktop baseline", () => {
    const baseline = styles.search(
      /\.results-toolbar-display\s*\{\s*justify-content:\s*flex-end;/
    );
    const phoneOverrides = Array.from(
      styles.matchAll(
        /\.results-toolbar-display\s*\{\s*width:\s*100%;\s*justify-content:\s*flex-start;/g
      )
    );
    const phoneOverride = phoneOverrides.at(-1)?.index ?? -1;

    expect(baseline).toBeGreaterThan(-1);
    expect(phoneOverride).toBeGreaterThan(baseline);
  });

  it("lets the scenario-chip wrapper span the ultrawide composer grid", () => {
    expect(styles).toMatch(
      /\.scenario-workspace\.is-first-run\s+\.scenario-chips-wrap\s*\{\s*grid-column:\s*1\s*\/\s*-1;/
    );
  });

  it("keeps standalone overlay state out of the saved-scenario panel", () => {
    const savedScenariosPanel = readFileSync("src/SavedScenariosPanel.tsx", "utf8");

    expect(savedScenariosPanel).not.toContain('from "./useOverlay"');
    expect(savedScenariosPanel).not.toMatch(/\bconfirmDelete\.open\(/);
  });
});
