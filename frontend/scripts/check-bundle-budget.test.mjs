import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  CHART_BUDGET_BYTES,
  MAIN_BUDGET_BYTES,
  checkBundleBudget
} from "./check-bundle-budget.mjs";

async function buildFixture(mainBytes, plotlyBytes, factoryBytes = 512) {
  const root = await mkdtemp(join(tmpdir(), "nami-bundle-budget-"));
  const assets = join(root, "assets");
  await mkdir(assets);
  const pseudoRandom = (length, seed) => {
    const bytes = Buffer.alloc(length);
    let state = seed;
    for (let index = 0; index < length; index += 1) {
      state ^= state << 13;
      state ^= state >>> 17;
      state ^= state << 5;
      bytes[index] = state & 0xff;
    }
    return bytes;
  };
  await writeFile(join(assets, "index-test.js"), pseudoRandom(mainBytes, 0x12345678));
  await writeFile(
    join(assets, "plotly-finance.min-test.js"),
    pseudoRandom(plotlyBytes, 0x2468ace)
  );
  await writeFile(join(assets, "factory-test.js"), pseudoRandom(factoryBytes, 0x13579bdf));
  return root;
}

test("accepts gzip assets within both release limits", async () => {
  const dist = await buildFixture(512, 1024);
  const measurements = await checkBundleBudget(dist);

  assert.equal(measurements.main.limitBytes, MAIN_BUDGET_BYTES);
  assert.equal(measurements.chart.limitBytes, CHART_BUDGET_BYTES);
  assert.deepEqual(measurements.chart.files, [
    "plotly-finance.min-test.js",
    "factory-test.js"
  ]);
  assert.ok(measurements.main.gzipBytes < measurements.main.limitBytes);
  assert.ok(measurements.chart.gzipBytes < measurements.chart.limitBytes);
});

test("reports the measured gzip size and limit for every breached asset", async () => {
  const dist = await buildFixture(MAIN_BUDGET_BYTES * 3, CHART_BUDGET_BYTES * 3);

  await assert.rejects(
    checkBundleBudget(dist),
    (error) =>
      error instanceof Error &&
      /initial\/main JavaScript: measured .* KiB gzip; limit 100\.00 KiB/.test(error.message) &&
      /lazy chart JavaScript \(plotly-finance\.min-test\.js \+ factory-test\.js\): measured .* KiB gzip; limit 425\.00 KiB/.test(
        error.message
      )
  );
});

test("counts react-plotly factory growth against the lazy chart budget", async () => {
  const dist = await buildFixture(512, 512, CHART_BUDGET_BYTES * 3);

  await assert.rejects(
    checkBundleBudget(dist),
    (error) =>
      error instanceof Error &&
      /lazy chart JavaScript \(plotly-finance\.min-test\.js \+ factory-test\.js\): measured .* KiB gzip; limit 425\.00 KiB/.test(
        error.message
      )
  );
});

test("fails closed when a required release asset cannot be identified", async () => {
  const root = await mkdtemp(join(tmpdir(), "nami-bundle-budget-"));
  await mkdir(join(root, "assets"));

  await assert.rejects(
    checkBundleBudget(root),
    /Expected exactly one initial\/main JavaScript asset, found 0/
  );
});
