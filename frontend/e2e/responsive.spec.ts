import { expect, test } from "@playwright/test";
import {
  compactControlViolations,
  expectCleanNetworkPolicy,
  expectNoDocumentOverflow,
  installApiMocks,
  setPersistedTheme,
  viewports
} from "./fixtures";

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

    expectCleanNetworkPolicy(api);
  });
}

test("200% text scaling proxy keeps the page within the phone viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const api = await installApiMocks(page);
  await page.goto("/");
  await page.addStyleTag({ content: "html { font-size: 200% !important; }" });

  const overflow = await expectNoDocumentOverflow(page);
  expect(overflow.scrollWidth, JSON.stringify(overflow.offenders)).toBeLessThanOrEqual(
    overflow.clientWidth + 1
  );
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

for (const theme of ["dark", "light"] as const) {
  for (const viewport of [
    { width: 390, height: 844 },
    { width: 1440, height: 900 }
  ]) {
    test(`Quant V2 result is simple in ${theme} at ${viewport.width}px`, async ({ page }) => {
      await setPersistedTheme(page, theme);
      await page.setViewportSize(viewport);
      const api = await installApiMocks(page, { admin: true, quant: true });
      await page.goto("/");

      await page.getByLabel("Horizon").selectOption("63");
      await page.getByLabel("Severity").selectOption("2");
      await page.getByRole("button", { name: "Run hypothetical stress" }).click();

      await expect(page.getByRole("heading", { name: "Historical model range" })).toBeVisible();
      await expect(page.getByText(/Direct factor contribution/)).toBeVisible();
      await expect(page.getByRole("tab", { name: "Adjust" })).toHaveCount(0);
      await expect(page.getByRole("tab", { name: "Advanced" })).toHaveCount(0);
      expect(api.runPayloads.at(-1)).toMatchObject({ horizon: 63, severity: 2 });
      const overflow = await expectNoDocumentOverflow(page);
      expect(overflow.scrollWidth, JSON.stringify(overflow.offenders)).toBeLessThanOrEqual(
        overflow.clientWidth + 1
      );
      expectCleanNetworkPolicy(api);
    });
  }
}
