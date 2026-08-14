import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import {
  compactControlViolations,
  expectCleanNetworkPolicy,
  expectNoDocumentOverflow,
  installApiMocks,
  setPersistedTheme,
  viewports
} from "./fixtures";

async function expectNoSeriousAccessibilityViolations(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const violations = results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical"
  );
  expect(
    violations.map(({ id, impact, help, nodes }) => ({
      id,
      impact,
      help,
      targets: nodes.map((node) => node.target)
    }))
  ).toEqual([]);
}

for (const theme of ["dark", "light"] as const) {
  test(`${theme} theme stays responsive across the release width matrix`, async ({ page }) => {
    await setPersistedTheme(page, theme);
    const api = await installApiMocks(page);
    await page.goto("/");
    await expect(page.getByText("Demo mode")).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);

    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      const overflow = await expectNoDocumentOverflow(page);
      expect(
        overflow.scrollWidth,
        `${theme} at ${viewport.width}px: ${JSON.stringify(overflow.offenders)}`
      ).toBeLessThanOrEqual(overflow.clientWidth + 1);
      if (viewport.width <= 1079) {
        expect(
          await compactControlViolations(page),
          `${theme} compact controls at ${viewport.width}px`
        ).toEqual([]);
      }
    }

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByRole("button", { name: "Run hypothetical stress" }).click();
    await expect(page.getByRole("group", { name: "Contribution waterfall chart" })).toBeVisible();

    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      await expect(page.getByRole("group", { name: "Contribution waterfall chart" })).toHaveAttribute(
        "data-orientation",
        viewport.width <= 640 ? "horizontal" : "vertical"
      );
      const overflow = await expectNoDocumentOverflow(page);
      expect(
        overflow.scrollWidth,
        `${theme} results at ${viewport.width}px: ${JSON.stringify(overflow.offenders)}`
      ).toBeLessThanOrEqual(overflow.clientWidth + 1);
    }

    await page.setViewportSize({ width: 1440, height: 900 });
    await expectNoSeriousAccessibilityViolations(page);

    expectCleanNetworkPolicy(api);
  });
}

test("200% text scaling proxy keeps the page within the phone viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const api = await installApiMocks(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Run hypothetical stress" }).click();
  await expect(page.getByRole("group", { name: "Contribution waterfall chart" })).toBeVisible();
  await page.addStyleTag({ content: "html { font-size: 200% !important; }" });

  const overflow = await expectNoDocumentOverflow(page);
  expect(overflow.scrollWidth, JSON.stringify(overflow.offenders)).toBeLessThanOrEqual(
    overflow.clientWidth + 1
  );
  expectCleanNetworkPolicy(api);
});

test("phone exposure rows wrap labels above a dedicated bar row", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 });
  const api = await installApiMocks(page);
  await page.goto("/");
  await page.getByRole("tab", { name: "Your book" }).click();
  await page.getByRole("button", { name: "Profile this book" }).click();

  const row = page.getByRole("list", { name: "Portfolio factor exposures" }).getByRole("listitem").first();
  const label = row.locator(".exposure-bar-label");
  const track = row.locator(".exposure-bar-track");
  await expect(label).toHaveCSS("white-space", "normal");
  const [labelBox, trackBox] = await Promise.all([label.boundingBox(), track.boundingBox()]);
  expect(labelBox).not.toBeNull();
  expect(trackBox).not.toBeNull();
  expect(trackBox!.y).toBeGreaterThanOrEqual(labelBox!.y + labelBox!.height - 1);

  const overflow = await expectNoDocumentOverflow(page);
  expect(overflow.scrollWidth, JSON.stringify(overflow.offenders)).toBeLessThanOrEqual(
    overflow.clientWidth + 1
  );
  expectCleanNetworkPolicy(api);
});

test("phone chart keeps its maximum-width tooltip inside the plot", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 });
  const api = await installApiMocks(page);
  await page.goto("/");
  await page.addStyleTag({ content: ".waterfall-tooltip { width: 240px !important; }" });
  await page.getByRole("button", { name: "Run hypothetical stress" }).click();

  const chart = page.getByTestId("waterfall-chart");
  const firstBar = page.locator("[data-waterfall-bar]").first();
  await firstBar.dispatchEvent("pointermove", { clientX: 319, clientY: 120 });
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip).toBeVisible();

  const [chartBox, tooltipBox] = await Promise.all([chart.boundingBox(), tooltip.boundingBox()]);
  expect(chartBox).not.toBeNull();
  expect(tooltipBox).not.toBeNull();
  expect(tooltipBox!.x).toBeGreaterThanOrEqual(chartBox!.x + 7);
  expect(tooltipBox!.x + tooltipBox!.width).toBeLessThanOrEqual(
    chartBox!.x + chartBox!.width - 7
  );
  const overflow = await expectNoDocumentOverflow(page);
  expect(overflow.scrollWidth, JSON.stringify(overflow.offenders)).toBeLessThanOrEqual(
    overflow.clientWidth + 1
  );
  expectCleanNetworkPolicy(api);
});

test("the selected result tab persists across viewport and theme changes", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await setPersistedTheme(page, "dark");
  const api = await installApiMocks(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Run hypothetical stress" }).click();
  await page.getByRole("tab", { name: "Positions" }).click();
  await expect(page.getByRole("tab", { name: "Positions" })).toHaveAttribute(
    "aria-selected",
    "true"
  );

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await expect(page.getByRole("tab", { name: "Positions" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expectCleanNetworkPolicy(api);
});

test("@smoke run, chart, theme, fullscreen, and keyboard exit", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: false });
  });
  await page.setViewportSize({ width: 1280, height: 800 });
  await setPersistedTheme(page, "dark");
  const api = await installApiMocks(page);
  await page.goto("/");

  await expect(page.getByText("Demo mode")).toBeVisible();
  const runButton = page.getByRole("button", { name: "Run hypothetical stress" });
  await expect(runButton).toBeEnabled();
  await runButton.focus();
  await expect(runButton).toBeFocused();
  await page.keyboard.press("Enter");
  const chart = page.getByRole("group", { name: "Contribution waterfall chart" });
  await expect(chart).toBeVisible();

  const firstBar = page.locator("[data-waterfall-bar]").first();
  await firstBar.focus();
  await expect(page.getByRole("tooltip")).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.locator("[data-waterfall-bar]:focus")).toHaveCount(1);

  const themeButton = page.getByRole("button", { name: "Switch to light theme" });
  await themeButton.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  const fullscreen = page.getByRole("button", { name: "Expand contribution waterfall" });
  await fullscreen.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "contribution waterfall" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "contribution waterfall" })).toHaveCount(0);
  await expect(page.locator("body")).not.toHaveCSS("overflow", "hidden");
  expectCleanNetworkPolicy(api);
});

test("phone scenario strip can reach and select Custom", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 });
  const api = await installApiMocks(page);
  await page.goto("/");

  const custom = page.getByRole("radio", { name: "Custom" });
  await custom.scrollIntoViewIfNeeded();
  await expect(custom).toBeInViewport();
  await custom.click();
  await expect(custom).toHaveAttribute("aria-checked", "true");
  const strip = page.getByRole("radiogroup", { name: "Example scenarios" });
  expect(await strip.evaluate((node) => node.scrollWidth > node.clientWidth)).toBe(true);
  expectCleanNetworkPolicy(api);
});

test("setup drawer closes cleanly when compact layout becomes desktop", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  const api = await installApiMocks(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Open portfolio and access setup" }).click();
  await expect(page.getByRole("dialog", { name: "Portfolio and access settings" })).toBeVisible();
  await expect(page.locator("body")).toHaveCSS("overflow", "hidden");

  await page.setViewportSize({ width: 1280, height: 800 });
  await expect(page.getByRole("dialog", { name: "Portfolio and access settings" })).toHaveCount(0);
  await expect(page.locator("aside.rail")).toHaveCount(1);
  await expect(page.locator("body")).not.toHaveCSS("overflow", "hidden");
  expectCleanNetworkPolicy(api);
});

test("completed run lands on Drivers and fallback fullscreen exits before palette navigation", async ({
  page
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: false });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  const api = await installApiMocks(page, { admin: true });
  await page.goto("/");

  await page.getByRole("button", { name: "Run hypothetical stress" }).click();
  await expect(page.getByRole("tab", { name: "Drivers" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "What drove the P&L" })).toBeVisible();

  await page.getByRole("button", { name: "Expand contribution waterfall" }).click();
  await expect(page.getByRole("dialog", { name: "contribution waterfall" })).toBeVisible();
  await expect(page.locator("body")).toHaveCSS("overflow", "hidden");

  await page.keyboard.press("Control+K");
  await expect(page.getByRole("dialog", { name: "contribution waterfall" })).toHaveCount(0);
  await expect(page.getByRole("dialog", { name: "Command palette" })).toBeVisible();
  await expect(page.locator("body")).toHaveCSS("overflow", "hidden");
  await page.getByRole("combobox", { name: "Command search" }).fill("Go to Your book");
  await page.getByRole("option", { name: "Go to Your book" }).click();
  await expect(page.getByRole("tab", { name: "Your book" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  await expect(page.locator("body")).not.toHaveCSS("overflow", "hidden");
  expectCleanNetworkPolicy(api);
});

test("results keep one export and expose Edit & re-run only for saved origins", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const api = await installApiMocks(page, { admin: true, savedScenario: true });
  await page.goto("/");

  await page.getByRole("button", { name: "Run hypothetical stress" }).click();
  await expect(page.getByRole("button", { name: "Export all results" })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Edit & re-run" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Pin to compare" })).toHaveCount(0);

  await page.getByRole("tab", { name: "Library" }).click();
  await page.getByRole("button", { name: "Quarterly stress", exact: true }).click();
  await expect(page.getByRole("tab", { name: "Scenario" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  await expect(page.getByRole("button", { name: "Edit & re-run" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Export all results" })).toHaveCount(1);
  expectCleanNetworkPolicy(api);
});

test("save and purge confirmations yield to the command palette", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const api = await installApiMocks(page, { admin: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Run hypothetical stress" }).click();

  await page.getByRole("button", { name: "Save scenario" }).click();
  await expect(page.getByRole("dialog", { name: "Save scenario" })).toBeVisible();
  await page.keyboard.press("Control+K");
  await expect(page.getByRole("dialog", { name: "Save scenario" })).toHaveCount(0);
  await expect(page.getByRole("dialog", { name: "Command palette" })).toBeVisible();
  await expect(page.locator("body")).toHaveCSS("overflow", "hidden");
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Open operations console" }).click();
  await page.getByRole("button", { name: "Purge all data…" }).click();
  await expect(page.getByRole("dialog", { name: "Purge all saved data" })).toBeVisible();
  await page.keyboard.press("Control+K");
  await expect(page.getByRole("dialog", { name: "Purge all saved data" })).toHaveCount(0);
  await expect(page.getByRole("dialog", { name: "Command palette" })).toBeVisible();
  await expect(page.locator("[role=dialog]:visible")).toHaveCount(1);
  await expect(page.locator("body")).toHaveCSS("overflow", "hidden");
  expectCleanNetworkPolicy(api);
});

test("a transient transport failure retries once and leaves no startup banner", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const api = await installApiMocks(page, { failFirstAccessTransport: true });
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Explore a stress narrative" })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  // The development server runs React StrictMode, so its discarded first
  // effect may finish one bounded retry after the active effect succeeds.
  // The third request is that retry; production has only the first two.
  await expect.poll(api.accessAttempts).toBe(3);
  const settledAttempts = api.accessAttempts();
  await page.waitForTimeout(1_000);
  expect(api.accessAttempts()).toBe(settledAttempts);
  expectCleanNetworkPolicy(api);
});
