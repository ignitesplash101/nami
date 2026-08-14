import { readdir, readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { gzipSync } from "node:zlib";

export const INITIAL_BUDGET_BYTES = 100 * 1024;
export const CHART_BUDGET_BYTES = 45 * 1024;
export const CSS_BUDGET_BYTES = 25 * 1024;

const CHART_ENTRY = "src/results/WaterfallSvg.tsx";

function kib(bytes) {
  return `${(bytes / 1024).toFixed(2)} KiB`;
}

function exactlyOne(entries, label) {
  if (entries.length !== 1) {
    throw new Error(`Expected exactly one ${label}, found ${entries.length}.`);
  }
  return entries[0];
}

function collectStaticJavaScript(manifest, rootKey) {
  const visited = new Set();
  const files = new Set();

  function visit(key) {
    if (visited.has(key)) return;
    visited.add(key);
    const entry = manifest[key];
    if (!entry) throw new Error(`Manifest import ${key} has no matching entry.`);
    if (typeof entry.file === "string" && entry.file.endsWith(".js")) files.add(entry.file);
    for (const importedKey of entry.imports ?? []) visit(importedKey);
  }

  visit(rootKey);
  return files;
}

async function measureFiles(distDir, files, label, limitBytes) {
  if (files.length === 0) throw new Error(`Expected at least one ${label} asset, found 0.`);
  const gzipBytes = (
    await Promise.all(
      files.map(async (file) => {
        const source = await readFile(resolve(distDir, file));
        return gzipSync(source, { level: 9 }).byteLength;
      })
    )
  ).reduce((total, bytes) => total + bytes, 0);
  return { files, gzipBytes, limitBytes, label };
}

function measurementLabel({ label, files }) {
  return `${label} (${files.join(" + ")})`;
}

export async function checkBundleBudget(distDir = "dist") {
  const manifestPath = resolve(distDir, ".vite", "manifest.json");
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  const entries = Object.entries(manifest);
  const initialKey = exactlyOne(
    entries.filter(([, entry]) => entry.isEntry).map(([key]) => key),
    "initial manifest entry"
  );
  const chartKey = exactlyOne(
    entries
      .filter(([key]) => key.replaceAll("\\", "/") === CHART_ENTRY)
      .map(([key]) => key),
    "lazy chart manifest entry"
  );

  const initialGraph = collectStaticJavaScript(manifest, initialKey);
  const chartGraph = collectStaticJavaScript(manifest, chartKey);
  const chartOnlyGraph = new Set([...chartGraph].filter((file) => !initialGraph.has(file)));
  const assetNames = await readdir(resolve(distDir, "assets"));
  const cssFiles = assetNames
    .filter((file) => file.endsWith(".css"))
    .map((file) => `assets/${file}`);

  const [initial, chart, css] = await Promise.all([
    measureFiles(
      distDir,
      [...initialGraph].sort(),
      "initial JavaScript",
      INITIAL_BUDGET_BYTES
    ),
    measureFiles(
      distDir,
      [...chartOnlyGraph].sort(),
      "complete lazy chart path",
      CHART_BUDGET_BYTES
    ),
    measureFiles(distDir, cssFiles.sort(), "CSS", CSS_BUDGET_BYTES)
  ]);
  const measurements = { initial, chart, css };
  const breaches = Object.values(measurements).filter(
    ({ gzipBytes, limitBytes }) => gzipBytes > limitBytes
  );
  if (breaches.length) {
    throw new Error(
      breaches
        .map(
          (measurement) =>
            `${measurementLabel(measurement)}: measured ${kib(
              measurement.gzipBytes
            )} gzip; limit ${kib(measurement.limitBytes)}`
        )
        .join("\n")
    );
  }
  return measurements;
}

async function main() {
  const measurements = await checkBundleBudget(process.argv[2] ?? "dist");
  for (const measurement of Object.values(measurements)) {
    console.log(
      `[bundle-budget] ${measurementLabel(measurement)}: ${kib(
        measurement.gzipBytes
      )} gzip / ${kib(measurement.limitBytes)} limit`
    );
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch((error) => {
    console.error(`[bundle-budget] ${error instanceof Error ? error.message : error}`);
    process.exitCode = 1;
  });
}
