import type {
  AccessResponse,
  PortfolioValidationResponse,
  SamplePortfolio,
  SampleScenario,
  ScenarioResult,
  ScenarioRunResponse
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

export function decomposeScenario(result: ScenarioResult): Promise<ScenarioRunResponse> {
  return requestJson<ScenarioRunResponse>("/api/scenarios/decompose", {
    method: "POST",
    body: JSON.stringify({ result })
  });
}

export async function getMethodology(): Promise<string> {
  const response = await fetch("/api/docs/methodology", { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.text();
}

