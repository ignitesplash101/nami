import { readdir, readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { gzipSync } from "node:zlib";

export const MAIN_BUDGET_BYTES = 100 * 1024;
export const CHART_BUDGET_BYTES = 425 * 1024;

const assetContracts = [
  {
    key: "main",
    label: "initial/main JavaScript",
    patterns: [/^index-[\w-]+\.js$/],
    limitBytes: MAIN_BUDGET_BYTES
  },
  {
    key: "chart",
    label: "lazy chart JavaScript",
    patterns: [/^plotly-finance\.min-[\w-]+\.js$/, /^factory-[\w-]+\.js$/],
    limitBytes: CHART_BUDGET_BYTES
  }
];

function kib(bytes) {
  return `${(bytes / 1024).toFixed(2)} KiB`;
}

async function measureAsset(assetsDir, files, contract) {
  const matchesByPattern = contract.patterns.map((pattern) =>
    files.filter((file) => pattern.test(file))
  );
  const invalidMatch = matchesByPattern.findIndex((matches) => matches.length !== 1);
  if (invalidMatch !== -1) {
    const matches = matchesByPattern[invalidMatch];
    const qualifier = contract.patterns.length > 1 ? ` for ${contract.patterns[invalidMatch]}` : "";
    throw new Error(
      `Expected exactly one ${contract.label} asset${qualifier}, found ${matches.length}.`
    );
  }
  const matchedFiles = matchesByPattern.map(([file]) => file);
  const gzipBytes = (
    await Promise.all(
      matchedFiles.map(async (file) => {
        const source = await readFile(resolve(assetsDir, file));
        return gzipSync(source, { level: 9 }).byteLength;
      })
    )
  ).reduce((total, bytes) => total + bytes, 0);
  return {
    files: matchedFiles,
    gzipBytes,
    limitBytes: contract.limitBytes,
    label: contract.label
  };
}

function measurementLabel({ label, files }) {
  return files.length > 1 ? `${label} (${files.join(" + ")})` : label;
}

export async function checkBundleBudget(distDir = "dist") {
  const assetsDir = resolve(distDir, "assets");
  const files = await readdir(assetsDir);
  const measured = await Promise.all(
    assetContracts.map((contract) => measureAsset(assetsDir, files, contract))
  );
  const measurements = Object.fromEntries(
    measured.map((measurement, index) => [assetContracts[index].key, measurement])
  );
  const breaches = measured.filter(({ gzipBytes, limitBytes }) => gzipBytes > limitBytes);
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
      )} gzip / ${kib(
        measurement.limitBytes
      )} limit`
    );
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch((error) => {
    console.error(`[bundle-budget] ${error instanceof Error ? error.message : error}`);
    process.exitCode = 1;
  });
}
