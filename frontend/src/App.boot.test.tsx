import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { ApiError } from "./api";
import { BOOT_RETRY_DELAYS_MS } from "./boot";
import type { AccessResponse, SamplePortfolio, SampleScenario } from "./types";

const apiMocks = vi.hoisted(() => ({
  getAccess: vi.fn(),
  getSamplePortfolios: vi.fn(),
  getSampleScenarios: vi.fn(),
  getFactors: vi.fn(),
  getMethodology: vi.fn(),
  getSavedScenario: vi.fn(),
  getTickerMetadata: vi.fn(),
  listSavedScenarios: vi.fn(),
  listSavedPortfolios: vi.fn()
}));

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    getAccess: () => apiMocks.getAccess(),
    getSamplePortfolios: () => apiMocks.getSamplePortfolios(),
    getSampleScenarios: () => apiMocks.getSampleScenarios(),
    getFactors: () => apiMocks.getFactors(),
    getMethodology: () => apiMocks.getMethodology(),
    getSavedScenario: (id: string) => apiMocks.getSavedScenario(id),
    getTickerMetadata: () => apiMocks.getTickerMetadata(),
    listSavedScenarios: () => apiMocks.listSavedScenarios(),
    listSavedPortfolios: () => apiMocks.listSavedPortfolios()
  };
});

const access: AccessResponse = {
  access_mode: "visitor",
  admin_available: true,
  latest_market_date: "2026-07-13",
  permissions: {
    custom_portfolio: false,
    free_text_scenario: false,
    narrative_decomposition: false
  }
};

const adminAccess: AccessResponse = {
  ...access,
  access_mode: "admin",
  permissions: {
    custom_portfolio: true,
    free_text_scenario: true,
    narrative_decomposition: true
  }
};

const portfolios: SamplePortfolio[] = [
  {
    key: "sample-book",
    name: "Sample book",
    description: "A sample portfolio",
    holdings: { AAPL: 0.6, MSFT: 0.4 },
    benchmark: "SPY"
  }
];

const scenarios: SampleScenario[] = [
  { key: "sample-shock", name: "Sample shock", text: "A broad market selloff" }
];

async function flushAsyncWork(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("App bootstrap recovery", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    for (const mock of Object.values(apiMocks)) mock.mockReset();
    apiMocks.getAccess.mockResolvedValue(access);
    apiMocks.getSamplePortfolios.mockResolvedValue(portfolios);
    apiMocks.getSampleScenarios.mockResolvedValue(scenarios);
    apiMocks.getFactors.mockResolvedValue([]);
    apiMocks.getMethodology.mockResolvedValue("# Methodology");
    apiMocks.getTickerMetadata.mockResolvedValue({});
    apiMocks.listSavedScenarios.mockResolvedValue([
      {
        id: "saved-1",
        name: "Quarterly stress",
        tags: [],
        created_at: "2026-07-14T00:00:00Z",
        owner_label: null,
        portfolio_name: "Global quality",
        portfolio_key: "sample-book",
        requested_as_of_date: "2026-07-14",
        effective_as_of_date: "2026-07-14",
        narrative_mode: "grounded_current",
        total_pnl: -0.12
      }
    ]);
    apiMocks.listSavedPortfolios.mockResolvedValue([]);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("recovers a failed boot on reconnect and ignores reconnects after success", async () => {
    const interrupted = new ApiError({
      status: null,
      detail: "Network request failed.",
      kind: "network"
    });
    apiMocks.getAccess
      .mockRejectedValueOnce(interrupted)
      .mockRejectedValueOnce(interrupted)
      .mockRejectedValueOnce(interrupted)
      .mockResolvedValue(access);

    const view = render(<App />);
    expect(apiMocks.getAccess).toHaveBeenCalledTimes(1);

    await act(() => vi.advanceTimersByTimeAsync(BOOT_RETRY_DELAYS_MS[0]));
    expect(apiMocks.getAccess).toHaveBeenCalledTimes(2);
    await act(() => vi.advanceTimersByTimeAsync(BOOT_RETRY_DELAYS_MS[1]));
    await flushAsyncWork();

    expect(apiMocks.getAccess).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("alert")).toHaveTextContent(/interrupted while loading/i);
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();

    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });
    await flushAsyncWork();

    expect(apiMocks.getAccess).toHaveBeenCalledTimes(4);
    expect(screen.queryByText(/interrupted while loading/i)).not.toBeInTheDocument();
    expect(screen.getByText("Demo mode")).toBeInTheDocument();

    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });
    await flushAsyncWork();
    expect(apiMocks.getAccess).toHaveBeenCalledTimes(4);

    view.unmount();
  });

  it("releases a saved-delete overlay when an admin session expires", async () => {
    apiMocks.getAccess.mockReset();
    apiMocks.getAccess.mockResolvedValueOnce(adminAccess).mockResolvedValue(access);

    const view = render(<App />);
    await flushAsyncWork();

    act(() => screen.getByRole("tab", { name: "Library" }).click());
    await flushAsyncWork();
    const deleteButton = screen.getByRole("button", { name: "Delete Quarterly stress" });
    act(() => deleteButton.click());

    expect(screen.getByRole("dialog", { name: "Delete saved scenario" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(apiMocks.getAccess).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("dialog", { name: "Delete saved scenario" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Library" })).toBeNull();
    expect(document.body.style.overflow).toBe("");

    view.unmount();
  });
});
