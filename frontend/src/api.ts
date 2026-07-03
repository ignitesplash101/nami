import type {
  AccessResponse,
  AuditEntry,
  BookProfile,
  EventsReplay,
  FactorMetadata,
  PortfolioSnapshotRecord,
  PortfolioValidationResponse,
  PurgeCounts,
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
  StatusResponse,
  TickerMetadata,
  UsageSummary
} from "./types";

// --- Typed API errors -------------------------------------------------------
//
// The `X-Error-Code` response header (and the `code` field on SSE error events)
// is the machine-readable error contract; detail strings are display-only and
// may be LLM-generated free text. Where no code is present, `kind` derives from
// the HTTP status alone.

export type ApiErrorKind =
  | "rate_limited"
  | "budget_exhausted"
  | "run_cap"
  | "expired"
  | "too_large"
  | "validation"
  | "rerun_required"
  | "marking_unavailable"
  | "auth"
  | "forbidden"
  | "network"
  | "timeout"
  | "cancelled"
  | "unavailable"
  | "unknown";

const KNOWN_ERROR_CODES: ReadonlySet<string> = new Set([
  "rate_limited",
  "budget_exhausted",
  "run_cap",
  "expired",
  "too_large",
  "validation",
  "rerun_required",
  "marking_unavailable",
  "auth",
  "forbidden",
  "unavailable",
  "unknown"
]);

export function deriveErrorKind(status: number | null, code: string | null): ApiErrorKind {
  if (code && KNOWN_ERROR_CODES.has(code)) return code as ApiErrorKind;
  if (status === null) return "network";
  switch (status) {
    case 401:
      return "auth";
    case 403:
      return "forbidden";
    case 410:
      return "expired";
    case 413:
      return "too_large";
    case 422:
      return "validation";
    case 429:
      return "rate_limited";
    case 503:
      return "unavailable";
    default:
      return "unknown";
  }
}

function headerOf(response: Response, name: string): string | null {
  try {
    return response.headers?.get(name) ?? null;
  } catch {
    return null;
  }
}

export class ApiError extends Error {
  readonly status: number | null;
  readonly detail: string;
  readonly requestId: string | null;
  readonly kind: ApiErrorKind;

  constructor(init: {
    status: number | null;
    detail: string;
    requestId?: string | null;
    kind: ApiErrorKind;
  }) {
    // message === detail so components not yet migrated to ErrorNotice keep
    // rendering something sensible via `exc.message`.
    super(init.detail);
    this.name = "ApiError";
    this.status = init.status;
    this.detail = init.detail;
    this.requestId = init.requestId ?? null;
    this.kind = init.kind;
  }

  static async fromResponse(response: Response): Promise<ApiError> {
    // Read the body ONCE as text, then try to parse JSON — reading json() then
    // text() on a failed parse throws "body stream already read" and masks the
    // real server error.
    let detail = `${response.status} ${response.statusText}`;
    try {
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
    } catch {
      // Body unreadable — keep the status line as the detail.
    }
    return new ApiError({
      status: response.status,
      detail,
      requestId: headerOf(response, "X-Request-ID"),
      kind: deriveErrorKind(response.status, headerOf(response, "X-Error-Code"))
    });
  }

  static network(_cause: unknown): ApiError {
    return new ApiError({
      status: null,
      detail: "Network request failed.",
      kind: "network"
    });
  }

  /** In-band SSE errors arrive over a healthy HTTP 200 connection — an absent
   * code maps to "unknown", NEVER "network". */
  static fromSseError(
    message: string,
    code: string | null | undefined,
    requestId: string | null
  ): ApiError {
    const kind = code && KNOWN_ERROR_CODES.has(code) ? (code as ApiErrorKind) : "unknown";
    return new ApiError({ status: null, detail: message, requestId, kind });
  }
}

/** Normalize any thrown value into an ApiError (user aborts become "cancelled"). */
export function toApiError(exc: unknown): ApiError {
  if (exc instanceof ApiError) return exc;
  if (exc instanceof Error && exc.name === "AbortError") {
    return new ApiError({ status: null, detail: "Run cancelled.", kind: "cancelled" });
  }
  const detail = exc instanceof Error ? exc.message : String(exc);
  return new ApiError({ status: null, detail, kind: "unknown" });
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {})
      },
      ...init
    });
  } catch (exc) {
    throw ApiError.network(exc);
  }
  if (!response.ok) {
    throw await ApiError.fromResponse(response);
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

export function profileBook(payload: {
  portfolio_key?: string;
  portfolio_name?: string;
  portfolio_holdings?: Record<string, number>;
}): Promise<BookProfile> {
  return requestJson<BookProfile>("/api/portfolios/profile", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function replayEvents(payload: {
  portfolio_key?: string;
  portfolio_name?: string;
  portfolio_holdings?: Record<string, number>;
}): Promise<EventsReplay> {
  return requestJson<EventsReplay>("/api/portfolios/events-replay", {
    method: "POST",
    body: JSON.stringify(payload)
  });
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

// Abort the stream if no progress event arrives for this long. The run pipeline
// is ~10-20s and the slowest single stage (grounded narrative) is well under
// this, so an idle gap this large means the server stopped responding.
const RUN_SSE_IDLE_TIMEOUT_MS = 60_000;
// Decomposition gaps between subset events are much longer (each subset is a
// full pipeline rerun), so its idle window is wider.
const DECOMPOSE_SSE_IDLE_TIMEOUT_MS = 120_000;

interface StreamSseOptions {
  idleTimeoutMs: number;
  signal?: AbortSignal;
  onEvent: (event: SseProgressEvent) => void;
}

/** Shared SSE reader: owns the AbortController, external-signal forwarding,
 * idle timeout, frame parsing, and the error ladder (timeout / cancelled /
 * in-band error event / network). */
async function streamSse(url: string, body: unknown, opts: StreamSseOptions): Promise<void> {
  const controller = new AbortController();
  let timedOut = false;
  let cancelled = opts.signal?.aborted ?? false;
  const cancelledError = () =>
    new ApiError({ status: null, detail: "Run cancelled.", kind: "cancelled" });
  if (cancelled) throw cancelledError();

  const onExternalAbort = () => {
    cancelled = true;
    controller.abort();
  };
  opts.signal?.addEventListener("abort", onExternalAbort, { once: true });

  let idleTimer: ReturnType<typeof setTimeout> | undefined;
  const clearIdle = () => {
    if (idleTimer !== undefined) clearTimeout(idleTimer);
  };
  const armIdle = () => {
    clearIdle();
    idleTimer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, opts.idleTimeoutMs);
  };
  const timeoutError = () =>
    new ApiError({
      status: null,
      detail:
        `Stream timed out — no progress for ${Math.round(opts.idleTimeoutMs / 1000)}s. ` +
        "The server may still finish and warm the cache, so retrying can be instant.",
      kind: "timeout"
    });
  const cleanup = () => {
    clearIdle();
    opts.signal?.removeEventListener("abort", onExternalAbort);
  };

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal
    });
  } catch (exc) {
    cleanup();
    if (cancelled) throw cancelledError();
    throw ApiError.network(exc);
  }
  const requestId = headerOf(response, "X-Request-ID");
  if (!response.ok) {
    cleanup();
    throw await ApiError.fromResponse(response);
  }
  if (!response.body) {
    cleanup();
    throw new ApiError({
      status: response.status,
      detail: "Stream response had no body.",
      requestId,
      kind: "unknown"
    });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  armIdle();
  try {
    while (true) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch (exc) {
        if (cancelled) throw cancelledError();
        if (timedOut) throw timeoutError();
        throw ApiError.network(exc);
      }
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });

      let separatorIdx;
      while ((separatorIdx = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, separatorIdx);
        buffer = buffer.slice(separatorIdx + 2);
        const dataLine = frame.split("\n").find((line) => line.startsWith("data: "));
        if (!dataLine) continue;
        const event: SseProgressEvent = JSON.parse(dataLine.slice("data: ".length));
        armIdle(); // progress arrived — reset the idle clock
        opts.onEvent(event);
        if (event.stage === "error") {
          throw ApiError.fromSseError(
            event.message ?? "Stream failed.",
            event.code ?? null,
            requestId
          );
        }
      }
    }
  } finally {
    cleanup();
  }
}

export async function runScenarioStream(
  payload: RunScenarioPayload,
  onProgress: (event: SseProgressEvent) => void,
  options?: { signal?: AbortSignal }
): Promise<ScenarioRunResponse> {
  let finalResult: ScenarioRunResponse | null = null;
  await streamSse("/api/scenarios/run-stream", payload, {
    idleTimeoutMs: RUN_SSE_IDLE_TIMEOUT_MS,
    signal: options?.signal,
    onEvent: (event) => {
      onProgress(event);
      if (event.stage === "done" && event.result) {
        finalResult = event.result;
      }
    }
  });
  if (!finalResult) {
    throw new ApiError({
      status: null,
      detail: "Scenario stream ended without a final result.",
      kind: "unknown"
    });
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
  onProgress: (done: number, total: number) => void,
  options?: { signal?: AbortSignal }
): Promise<ScenarioRunResponse> {
  let finalResult: ScenarioRunResponse | null = null;
  await streamSse(
    "/api/scenarios/decompose-stream",
    { result },
    {
      idleTimeoutMs: DECOMPOSE_SSE_IDLE_TIMEOUT_MS,
      signal: options?.signal,
      onEvent: (event) => {
        const raw = event as unknown as Record<string, unknown>;
        if (raw.stage === "subset") {
          onProgress(raw.done as number, raw.total as number);
        } else if (event.stage === "done" && event.result) {
          finalResult = event.result;
        }
      }
    }
  );
  if (!finalResult) {
    throw new ApiError({
      status: null,
      detail: "Decomposition stream ended without a result.",
      kind: "unknown"
    });
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

export async function deleteSavedScenario(id: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api/saved-scenarios/${encodeURIComponent(id)}`, {
      method: "DELETE",
      credentials: "same-origin"
    });
  } catch (exc) {
    throw ApiError.network(exc);
  }
  if (!response.ok && response.status !== 204) {
    throw await ApiError.fromResponse(response);
  }
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
  let response: Response;
  try {
    response = await fetch("/api/docs/methodology", { credentials: "same-origin" });
  } catch (exc) {
    throw ApiError.network(exc);
  }
  if (!response.ok) {
    throw await ApiError.fromResponse(response);
  }
  return response.text();
}

// --- Operations console (admin) ---

export function getStatus(): Promise<StatusResponse> {
  return requestJson<StatusResponse>("/api/status");
}

export function getUsage(): Promise<UsageSummary> {
  return requestJson<UsageSummary>("/api/usage");
}

export function getAuditLog(limit = 100): Promise<AuditEntry[]> {
  return requestJson<AuditEntry[]>(`/api/audit?limit=${limit}`);
}

/** Destructive: deletes all saved scenarios/portfolios/snapshots (audit log
 * survives). `confirm` must be the literal backend token — the UI only reaches
 * this through the type-to-confirm dialog. */
export function purgeAllData(confirm: string): Promise<PurgeCounts> {
  return requestJson<PurgeCounts>("/api/admin/purge", {
    method: "POST",
    body: JSON.stringify({ confirm })
  });
}

export async function downloadExport(): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch("/api/export", { credentials: "same-origin" });
  } catch (exc) {
    throw ApiError.network(exc);
  }
  if (!response.ok) {
    throw await ApiError.fromResponse(response);
  }
  return response.blob();
}
