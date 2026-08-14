import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  CHART_BUDGET_BYTES,
  CSS_BUDGET_BYTES,
  INITIAL_BUDGET_BYTES,
  checkBundleBudget
} from "./check-bundle-budget.mjs";

function pseudoRandom(length, seed) {
  const bytes = Buffer.alloc(length);
  let state = seed;
  for (let index = 0; index < length; index += 1) {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    bytes[index] = state & 0xff;
  }
  return bytes;
}

async function buildFixture({
  initialBytes = 512,
  sharedBytes = 512,
  chartBytes = 512,
  geometryBytes = 512,
  cssBytes = 512
} = {}) {
  const root = await mkdtemp(join(tmpdir(), "nami-bundle-budget-"));
  const assets = join(root, "assets");
  await mkdir(assets);
  await mkdir(join(root, ".vite"));

  const files = [
    ["index-test.js", initialBytes, 0x12345678],
    ["shared-test.js", sharedBytes, 0x13579bdf],
    ["WaterfallSvg-test.js", chartBytes, 0x2468ace],
    ["d3-scale-test.js", geometryBytes, 0x1020304],
    ["index-test.css", cssBytes, 0x5060708]
  ];
  await Promise.all(
    files.map(([name, bytes, seed]) =>
      writeFile(join(assets, name), pseudoRandom(bytes, seed))
    )
  );

  await writeFile(
    join(root, ".vite", "manifest.json"),
    JSON.stringify({
      "_shared.js": { file: "assets/shared-test.js" },
      "_d3-scale.js": { file: "assets/d3-scale-test.js" },
      "index.html": {
        file: "assets/index-test.js",
        isEntry: true,
        imports: ["_shared.js"],
        dynamicImports: ["src/results/WaterfallSvg.tsx"],
        css: ["assets/index-test.css"]
      },
      "src/results/WaterfallSvg.tsx": {
        file: "assets/WaterfallSvg-test.js",
        isDynamicEntry: true,
        imports: ["_shared.js", "_d3-scale.js"]
      }
    })
  );
  return root;
}

test("accepts manifest-derived initial, unique chart, and CSS graphs within release limits", async () => {
  const dist = await buildFixture();
  const measurements = await checkBundleBudget(dist);

  assert.equal(measurements.initial.limitBytes, INITIAL_BUDGET_BYTES);
  assert.equal(measurements.chart.limitBytes, CHART_BUDGET_BYTES);
  assert.equal(measurements.css.limitBytes, CSS_BUDGET_BYTES);
  assert.deepEqual(measurements.initial.files, [
    "assets/index-test.js",
    "assets/shared-test.js"
  ]);
  assert.deepEqual(measurements.chart.files, [
    "assets/WaterfallSvg-test.js",
    "assets/d3-scale-test.js"
  ]);
  assert.deepEqual(measurements.css.files, ["assets/index-test.css"]);
});

test("reports the measured gzip size and limit for every breached graph", async () => {
  const dist = await buildFixture({
    initialBytes: INITIAL_BUDGET_BYTES * 3,
    chartBytes: CHART_BUDGET_BYTES * 3,
    cssBytes: CSS_BUDGET_BYTES * 3
  });

  await assert.rejects(
    checkBundleBudget(dist),
    (error) =>
      error instanceof Error &&
      /initial JavaScript .* limit 100\.00 KiB/.test(error.message) &&
      /complete lazy chart path .* limit 45\.00 KiB/.test(error.message) &&
      /CSS .* limit 25\.00 KiB/.test(error.message)
  );
});

test("counts transitive chart-only imports while excluding code already paid for initially", async () => {
  const dist = await buildFixture({
    sharedBytes: CHART_BUDGET_BYTES * 3,
    geometryBytes: CHART_BUDGET_BYTES * 3
  });

  await assert.rejects(
    checkBundleBudget(dist),
    (error) =>
      error instanceof Error &&
      /complete lazy chart path .*d3-scale-test\.js.* limit 45\.00 KiB/.test(error.message) &&
      !/complete lazy chart path .*shared-test\.js/.test(error.message)
  );
});

test("fails closed when the manifest cannot identify the required chart entry", async () => {
  const dist = await buildFixture();
  await writeFile(
    join(dist, ".vite", "manifest.json"),
    JSON.stringify({
      "index.html": { file: "assets/index-test.js", isEntry: true }
    })
  );

  await assert.rejects(
    checkBundleBudget(dist),
    /Expected exactly one lazy chart manifest entry, found 0/
  );
});
