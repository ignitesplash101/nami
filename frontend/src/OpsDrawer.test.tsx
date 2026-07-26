import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OpsDrawer } from "./OpsDrawer";
import { ToastProvider } from "./toast";
import type { AuditEntry, MetricsResponse, StatusResponse, UsageSummary } from "./types";

const getUsageMock = vi.fn<() => Promise<UsageSummary>>();
const getStatusMock = vi.fn<() => Promise<StatusResponse>>();
const getAuditLogMock = vi.fn<() => Promise<AuditEntry[]>>();
const getMetricsMock = vi.fn<() => Promise<MetricsResponse>>();

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    getUsage: () => getUsageMock(),
    getStatus: () => getStatusMock(),
    getAuditLog: () => getAuditLogMock(),
    getMetrics: () => getMetricsMock()
  };
});

function usageFixture(): UsageSummary {
  return {
    day: "2026-06-10",
    runs: 12,
    calls: 31,
    tokens_in: 240_000,
    tokens_out: 51_000,
    spent_usd: 0.42,
    reserved_usd: 0.02,
    cost_cap_usd: 5,
    run_cap: 200
  };
}

function statusFixture(): StatusResponse {
  return {
    service: "nami",
    nami_engine_version: "0.1.0",
    prompt_version: "v8",
    model_id: "gemini-3.6-flash",
    environment: "test",
    ready: true,
    disclaimer: "d",
    rate_limits: { llm: "10/minute" },
    daily_cost_cap_usd: 5,
    daily_run_cap: 200,
    runs_today: 12,
    est_cost_today_usd: 0.42
  };
}

function auditFixture(): AuditEntry[] {
  return [
    {
      action: "scenario.save",
      target_type: "scenario",
      target_id: "abc12345xyz",
      request_id: "req-12345678",
      ip_hash: "h",
      at: new Date().toISOString()
    }
  ];
}

function renderDrawer(isOpen: boolean, onRequestPurge = vi.fn()) {
  render(
    <ToastProvider>
      <OpsDrawer isOpen={isOpen} onClose={() => {}} onRequestPurge={onRequestPurge} />
    </ToastProvider>
  );
  return { onRequestPurge };
}

function metricsFixture(): MetricsResponse {
  return {
    days: 7,
    entries_scanned: 40,
    truncated: false,
    synthetic_excluded: 16,
    include_synthetic: false,
    log_retention_days: 30,
    logs_available: true,
    logs_error: null,
    daily: [{ day: "2026-07-26", requests: 40, unique_visitors: 5, runs: 3, errors: 1 }],
    top_paths: [{ path: "/api/access", requests: 20 }],
    scenario_runs: [{ key: "covid_pandemic", runs: 3 }],
    portfolio_runs: [{ key: "msci_world", runs: 3 }],
    status_counts: { "200": 39, "429": 1 },
    top_errors: [{ path: "/api/scenarios/run", status: 429, count: 1 }],
    totals: {
      requests: 40,
      unique_visitors: 5,
      runs: 3,
      errors: 1,
      visitor_runs: 2,
      admin_runs: 1,
      cache_hit_rate: 0.5,
      latency_p50_ms: 20,
      latency_p95_ms: 90
    },
    cost_daily: [
      { day: "2026-07-26", runs: 3, calls: 9, spent_usd: 0.24, tokens_in: 100, tokens_out: 50 }
    ],
    cost_cap_usd: 25,
    run_cap: 500
  };
}

// Braces matter: a function returned from beforeEach would be registered as a
// vitest teardown callback (mockReset returns the callable mock).
beforeEach(() => {
  getUsageMock.mockReset();
  getStatusMock.mockReset();
  getAuditLogMock.mockReset();
  getMetricsMock.mockReset();
  getUsageMock.mockResolvedValue(usageFixture());
  getStatusMock.mockResolvedValue(statusFixture());
  getAuditLogMock.mockResolvedValue(auditFixture());
  getMetricsMock.mockResolvedValue(metricsFixture());
});

describe("OpsDrawer", () => {
  it("fetches nothing while closed", () => {
    renderDrawer(false);
    expect(getUsageMock).not.toHaveBeenCalled();
    expect(getStatusMock).not.toHaveBeenCalled();
    expect(getAuditLogMock).not.toHaveBeenCalled();
    expect(getMetricsMock).not.toHaveBeenCalled();
  });

  it("renders usage meters and audit rows when open", async () => {
    renderDrawer(true);
    await waitFor(() => expect(screen.getByText("12 / 200")).toBeInTheDocument());
    expect(screen.getByText(/\$0\.42/)).toBeInTheDocument();
    expect(screen.getByText("scenario.save")).toBeInTheDocument();
    expect(screen.getByText(/gemini-3\.6-flash/)).toBeInTheDocument();
  });

  it("renders metrics and discloses the excluded pre-warm traffic", async () => {
    renderDrawer(true);
    await waitFor(() => expect(screen.getByLabelText("Usage metrics")).toBeInTheDocument());
    expect(screen.getByText("covid_pandemic")).toBeInTheDocument();
    expect(screen.getByText(/16 pre-warm request\(s\) excluded/)).toBeInTheDocument();
    expect(screen.getByText("2 / 1")).toBeInTheDocument();
  });

  it("keeps the console usable when only the metrics fetch fails", async () => {
    getMetricsMock.mockRejectedValue(new Error("logging unavailable"));
    renderDrawer(true);
    // Usage/audit still render — Promise.all must not be all-or-nothing here.
    await waitFor(() => expect(screen.getByText("12 / 200")).toBeInTheDocument());
    expect(screen.queryByLabelText("Usage metrics")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("routes the purge button through onRequestPurge (drawer closes first)", async () => {
    const { onRequestPurge } = renderDrawer(true);
    await waitFor(() => expect(screen.getByText("12 / 200")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Purge all data…"));
    expect(onRequestPurge).toHaveBeenCalledOnce();
  });

  it("shows an inline error with retry when the fetch fails", async () => {
    getUsageMock.mockRejectedValue(new Error("nope"));
    renderDrawer(true);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });
});
