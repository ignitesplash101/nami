import type {
  AccessResponse,
  PortfolioValidationResponse,
  SamplePortfolio,
  SampleScenario,
  ScenarioAdjustRequest,
  ScenarioResult,
  ScenarioRunResponse,
  SseProgressEvent
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
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      detail = await response.text();
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
}

export function runScenario(payload: RunScenarioPayload): Promise<ScenarioRunResponse> {
  return requestJson<ScenarioRunResponse>("/api/scenarios/run", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function runScenarioStream(
  payload: RunScenarioPayload,
  onProgress: (event: SseProgressEvent) => void
): Promise<ScenarioRunResponse> {
  const response = await fetch("/api/scenarios/run-stream", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
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
      const dataLine = frame
        .split("\n")
        .find((line) => line.startsWith("data: "));
      if (!dataLine) continue;
      const event: SseProgressEvent = JSON.parse(dataLine.slice("data: ".length));
      onProgress(event);
      if (event.stage === "error") {
        throw new Error(event.message ?? "Scenario stream failed.");
      }
      if (event.stage === "done" && event.result) {
        finalResult = event.result;
      }
    }
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

export function adjustScenarioShocks(
  payload: ScenarioAdjustRequest
): Promise<ScenarioRunResponse> {
  return requestJson<ScenarioRunResponse>("/api/scenarios/adjust-shocks", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getMethodology(): Promise<string> {
  const response = await fetch("/api/docs/methodology", { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.text();
}

