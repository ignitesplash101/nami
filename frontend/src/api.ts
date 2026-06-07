import type {
  AccessResponse,
  FactorMetadata,
  PortfolioSnapshotRecord,
  PortfolioValidationResponse,
  SamplePortfolio,
  SampleScenario,
  SavedPortfolioRecord,
  SavedScenarioListItem,
  SavedScenarioRecord,
  ScenarioAdjustRequest,
  ScenarioReproducibility,
  ScenarioResult,
  ScenarioRunResponse,
  SseProgressEvent,
  TickerMetadata
} from "./types";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    ...init
  });
  if (!response.ok) {
    // Read the body ONCE as text, then try to parse JSON — reading json() then
    // text() on a failed parse throws "body stream already read" and masks the
    // real server error.
    let detail = `${response.status} ${response.statusText}`;
    const text = await response.text();
    if (text) {
      try {
        const body = JSON.parse(text);
        detail =
          typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
      } catch {
        detail = text;
      }
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function getAccess(): Promise<AccessResponse> {
  return requestJson<AccessResponse>("/api/access");
}

export function unlock(passcode: string): Promise<AccessResponse> {
  return requestJson<AccessResponse>("/api/auth/unlock", {
    method: "POST",
    body: JSON.stringify({ passcode })
  });
}

export function lock(): Promise<AccessResponse> {
  return requestJson<AccessResponse>("/api/auth/lock", { method: "POST", body: "{}" });
}

export function getSamplePortfolios(): Promise<SamplePortfolio[]> {
  return requestJson<SamplePortfolio[]>("/api/portfolios/samples");
}

export function getSampleScenarios(): Promise<SampleScenario[]> {
  return requestJson<SampleScenario[]>("/api/scenarios/samples");
}

export function getFactors(): Promise<FactorMetadata[]> {
  return requestJson<FactorMetadata[]>("/api/factors");
}

export async function getTickerMetadata(tickers?: string[]): Promise<TickerMetadata> {
  const query = tickers && tickers.length ? `?tickers=${encodeURIComponent(tickers.join(","))}` : "";
  const body = await requestJson<{ ticker_meta: TickerMetadata }>(
    `/api/portfolios/ticker-metadata${query}`
  );
  return body.ticker_meta;
}

export function validatePortfolio(
  holdings: Record<string, number>
): Promise<PortfolioValidationResponse> {
  return requestJson<PortfolioValidationResponse>("/api/portfolio/validate", {
    method: "POST",
    body: JSON.stringify({ holdings })
  });
}

export interface RunScenarioPayload {
  sample_scenario_key?: string;
  scenario_text?: string;
  portfolio_key?: string;
  portfolio_name?: string;
  portfolio_holdings?: Record<string, number>;
  // Backdated runs (admin-only): YYYY-MM-DD. Server resolves to the last NYSE
  // trading day on or before this date.
  as_of_date?: string;
  // Mark-to-market (admin-only). `position_quantities` = share counts (true MTM);
  // `portfolio_nav` = illustrative dollar scaling for weight-based books.
  position_quantities?: Record<string, number>;
  portfolio_nav?: number;
  reporting_currency?: string;
  // Benchmark ticker for relative (active) return. Custom books must pass one;
  // sample books fall back to their own assigned benchmark server-side.
  benchmark?: string;
}

export function runScenario(payload: RunScenarioPayload): Promise<ScenarioRunResponse> {
  return requestJson<ScenarioRunResponse>("/api/scenarios/run", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

// Abort the stream if no progress event arrives for this long. The whole
// pipeline is ~10-20s and the slowest single stage (grounded narrative) is well
// under this, so an idle gap this large means the server stopped responding.
const SSE_IDLE_TIMEOUT_MS = 60_000;

export async function runScenarioStream(
  payload: RunScenarioPayload,
  onProgress: (event: SseProgressEvent) => void
): Promise<ScenarioRunResponse> {
  const controller = new AbortController();
  let idleTimer: ReturnType<typeof setTimeout> | undefined;
  let timedOut = false;
  const clearIdle = () => {
    if (idleTimer !== undefined) clearTimeout(idleTimer);
  };
  const armIdle = () => {
    clearIdle();
    idleTimer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, SSE_IDLE_TIMEOUT_MS);
  };

  let response: Response;
  try {
    response = await fetch("/api/scenarios/run-stream", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal
    });
  } catch (exc) {
    clearIdle();
    throw exc;
  }
  if (!response.ok || !response.body) {
    clearIdle();
    throw new Error(`${response.status} ${response.statusText}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: ScenarioRunResponse | null = null;

  armIdle();
  try {
    while (true) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch (exc) {
        if (timedOut) {
          throw new Error(
            "Scenario timed out — the server stopped responding. Please try again."
          );
        }
        throw exc;
      }
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });

      let separatorIdx;
      while ((separatorIdx = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, separatorIdx);
        buffer = buffer.slice(separatorIdx + 2);
        const dataLine = frame
          .split("\n")
          .find((line) => line.startsWith("data: "));
        if (!dataLine) continue;
        const event: SseProgressEvent = JSON.parse(dataLine.slice("data: ".length));
        armIdle(); // progress arrived — reset the idle clock
        onProgress(event);
        if (event.stage === "error") {
          throw new Error(event.message ?? "Scenario stream failed.");
        }
        if (event.stage === "done" && event.result) {
          finalResult = event.result;
        }
      }
    }
  } finally {
    clearIdle();
  }

  if (!finalResult) {
    throw new Error("Scenario stream ended without a final result.");
  }
  return finalResult;
}

export function decomposeScenario(result: ScenarioResult): Promise<ScenarioRunResponse> {
  return requestJson<ScenarioRunResponse>("/api/scenarios/decompose", {
    method: "POST",
    body: JSON.stringify({ result })
  });
}

/** SSE variant: reports "{done}/{total} subset runs" while the 2^N pipeline reruns. */
export async function decomposeScenarioStream(
  result: ScenarioResult,
  onProgress: (done: number, total: number) => void
): Promise<ScenarioRunResponse> {
  const response = await fetch("/api/scenarios/decompose-stream", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ result })
  });
  if (!response.ok || !response.body) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: ScenarioRunResponse | null = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let separatorIdx;
    while ((separatorIdx = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, separatorIdx);
      buffer = buffer.slice(separatorIdx + 2);
      const dataLine = frame.split("\n").find((line) => line.startsWith("data: "));
      if (!dataLine) continue;
      const event = JSON.parse(dataLine.slice("data: ".length));
      if (event.stage === "subset") {
        onProgress(event.done as number, event.total as number);
      } else if (event.stage === "error") {
        throw new Error(event.message ?? "Decomposition failed.");
      } else if (event.stage === "done" && event.result) {
        finalResult = event.result as ScenarioRunResponse;
      }
    }
  }

  if (!finalResult) {
    throw new Error("Decomposition stream ended without a result.");
  }
  return finalResult;
}

export function adjustScenarioShocks(
  payload: ScenarioAdjustRequest
): Promise<ScenarioRunResponse> {
  return requestJson<ScenarioRunResponse>("/api/scenarios/adjust-shocks", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

// --- Saved analytics (Firestore-backed) ---

export interface SaveScenarioRequestPayload {
  name: string;
  tags: string[];
  notes: string;
  owner_label: string | null;
  result: ScenarioResult;
  analog_events_snapshot: Record<string, unknown>;
  reproducibility: ScenarioReproducibility;
  portfolio_snapshot_ref?: string | null;
}

export function saveScenario(
  payload: SaveScenarioRequestPayload
): Promise<SavedScenarioRecord> {
  return requestJson<SavedScenarioRecord>("/api/saved-scenarios", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function listSavedScenarios(tag?: string): Promise<SavedScenarioListItem[]> {
  const query = tag ? `?tag=${encodeURIComponent(tag)}` : "";
  return requestJson<SavedScenarioListItem[]>(`/api/saved-scenarios${query}`);
}

export function getSavedScenario(id: string): Promise<SavedScenarioRecord> {
  return requestJson<SavedScenarioRecord>(
    `/api/saved-scenarios/${encodeURIComponent(id)}`
  );
}

export function deleteSavedScenario(id: string): Promise<void> {
  return fetch(`/api/saved-scenarios/${encodeURIComponent(id)}`, {
    method: "DELETE",
    credentials: "same-origin"
  }).then((response) => {
    if (!response.ok && response.status !== 204) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
  });
}

export function savedScenarioDownloadUrl(id: string): string {
  return `/api/saved-scenarios/${encodeURIComponent(id)}/json`;
}

// --- Portfolios + snapshots ---

export function createPortfolio(payload: {
  name: string;
  description: string;
  owner_label: string | null;
}): Promise<SavedPortfolioRecord> {
  return requestJson<SavedPortfolioRecord>("/api/portfolios", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function listSavedPortfolios(): Promise<SavedPortfolioRecord[]> {
  return requestJson<SavedPortfolioRecord[]>("/api/portfolios");
}

export function createPortfolioSnapshot(
  portfolioId: string,
  payload: {
    as_of_date: string;
    holdings: Record<string, number>;
    notes: string;
    owner_label: string | null;
  }
): Promise<PortfolioSnapshotRecord> {
  return requestJson<PortfolioSnapshotRecord>(
    `/api/portfolios/${encodeURIComponent(portfolioId)}/snapshots`,
    { method: "POST", body: JSON.stringify(payload) }
  );
}

export function listPortfolioSnapshots(
  portfolioId: string
): Promise<PortfolioSnapshotRecord[]> {
  return requestJson<PortfolioSnapshotRecord[]>(
    `/api/portfolios/${encodeURIComponent(portfolioId)}/snapshots`
  );
}

export async function getMethodology(): Promise<string> {
  const response = await fetch("/api/docs/methodology", { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.text();
}
