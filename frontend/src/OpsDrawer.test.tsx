import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OpsDrawer } from "./OpsDrawer";
import { ToastProvider } from "./toast";
import type { AuditEntry, StatusResponse, UsageSummary } from "./types";

const getUsageMock = vi.fn<() => Promise<UsageSummary>>();
const getStatusMock = vi.fn<() => Promise<StatusResponse>>();
const getAuditLogMock = vi.fn<() => Promise<AuditEntry[]>>();

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    getUsage: () => getUsageMock(),
    getStatus: () => getStatusMock(),
    getAuditLog: () => getAuditLogMock()
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

// Braces matter: a function returned from beforeEach would be registered as a
// vitest teardown callback (mockReset returns the callable mock).
beforeEach(() => {
  getUsageMock.mockReset();
  getStatusMock.mockReset();
  getAuditLogMock.mockReset();
  getUsageMock.mockResolvedValue(usageFixture());
  getStatusMock.mockResolvedValue(statusFixture());
  getAuditLogMock.mockResolvedValue(auditFixture());
});

describe("OpsDrawer", () => {
  it("fetches nothing while closed", () => {
    renderDrawer(false);
    expect(getUsageMock).not.toHaveBeenCalled();
    expect(getStatusMock).not.toHaveBeenCalled();
    expect(getAuditLogMock).not.toHaveBeenCalled();
  });

  it("renders usage meters and audit rows when open", async () => {
    renderDrawer(true);
    await waitFor(() => expect(screen.getByText("12 / 200")).toBeInTheDocument());
    expect(screen.getByText(/\$0\.42/)).toBeInTheDocument();
    expect(screen.getByText("scenario.save")).toBeInTheDocument();
    expect(screen.getByText(/gemini-3\.6-flash/)).toBeInTheDocument();
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
