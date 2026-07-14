import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { validatePortfolio } from "../api";
import type { HoldingRow, HoldingUnits } from "../holdings";
import type {
  AccessResponse,
  PortfolioValidationResponse,
  SamplePortfolio
} from "../types";
import * as PortfolioPanelModule from "./PortfolioPanel";
import { PortfolioPanel } from "./PortfolioPanel";

vi.mock("../api", () => ({
  toApiError: (error: unknown) => ({ message: String(error) }),
  validatePortfolio: vi.fn()
}));

const adminAccess: AccessResponse = {
  access_mode: "admin",
  admin_available: true,
  latest_market_date: "2026-07-10",
  permissions: {
    custom_portfolio: true,
    free_text_scenario: true,
    narrative_decomposition: true
  }
};

const samplePortfolio: SamplePortfolio = {
  key: "sample",
  name: "Sample book",
  description: "A sample portfolio",
  holdings: {
    FIRST: 0.05,
    ZETA: 0.2,
    ALPHA: 0.2,
    SECOND: 0.1
  },
  benchmark: "URTH"
};

type SummaryFunction = (
  holdings: Record<string, number>,
  limit: number
) => {
  rows: Array<{ ticker: string; weight: number }>;
  coverage: number;
  remaining: number;
};

function validationResponse(errors: string[]): PortfolioValidationResponse {
  return {
    ok: errors.length === 0,
    errors,
    normalized_holdings: {},
    total_weight: 1
  };
}

function renderSamplePanel(holdings = samplePortfolio.holdings) {
  return render(
    <PortfolioPanel
      access={adminAccess}
      portfolios={[{ ...samplePortfolio, holdings }]}
      portfolioKey="sample"
      setPortfolioKey={() => {}}
      portfolioMode="sample"
      setPortfolioMode={() => {}}
      customName="Custom book"
      setCustomName={() => {}}
      customRows={[]}
      setCustomRows={() => {}}
      customUnits="weights"
      setCustomUnits={() => {}}
      customBenchmark=""
      setCustomBenchmark={() => {}}
    />
  );
}

function CustomPanelHarness({ initialRows }: { initialRows: HoldingRow[] }) {
  const [rows, setRows] = useState(initialRows);
  const [units, setUnits] = useState<HoldingUnits>("weights");

  return (
    <PortfolioPanel
      access={adminAccess}
      portfolios={[]}
      portfolioKey=""
      setPortfolioKey={() => {}}
      portfolioMode="custom"
      setPortfolioMode={() => {}}
      customName="Custom book"
      setCustomName={() => {}}
      customRows={rows}
      setCustomRows={setRows}
      customUnits={units}
      setCustomUnits={setUnits}
      customBenchmark=""
      setCustomBenchmark={() => {}}
    />
  );
}

describe("summarizeTopHoldings", () => {
  it("is exported as a pure summary helper", () => {
    expect(PortfolioPanelModule).toHaveProperty("summarizeTopHoldings");

    const summarize = (
      PortfolioPanelModule as typeof PortfolioPanelModule & {
        summarizeTopHoldings?: SummaryFunction;
      }
    ).summarizeTopHoldings;
    if (!summarize) return;

    const holdings = { ZETA: 0.2, SMALL: 0.05, ALPHA: 0.2, MID: 0.1 };
    const before = Object.entries(holdings);

    expect(summarize(holdings, 3)).toEqual({
      rows: [
        { ticker: "ALPHA", weight: 0.2 },
        { ticker: "ZETA", weight: 0.2 },
        { ticker: "MID", weight: 0.1 }
      ],
      coverage: 0.5,
      remaining: 1
    });
    expect(Object.entries(holdings)).toEqual(before);
    expect(summarize({}, 8)).toEqual({ rows: [], coverage: 0, remaining: 0 });
  });
});

describe("PortfolioPanel holdings context", () => {
  beforeEach(() => {
    vi.mocked(validatePortfolio).mockReset();
  });

  it("renders a weight-ranked preview with coverage and remaining-count context", () => {
    renderSamplePanel();

    expect(screen.getByText("ALPHA 20.0%")).toBeInTheDocument();
    expect(screen.getByText("ZETA 20.0%")).toBeInTheDocument();
    expect(screen.getByText("SECOND 10.0%")).toBeInTheDocument();
    expect(screen.getByText("Top 4 · 55.0% of book")).toBeInTheDocument();
    expect(screen.queryByText(/more$/)).not.toBeInTheDocument();
  });

  it("discloses omitted holdings and handles an empty book honestly", () => {
    const holdings = Object.fromEntries(
      Array.from({ length: 10 }, (_, index) => [`T${index}`, (10 - index) / 100])
    );
    const { rerender } = renderSamplePanel(holdings);

    expect(screen.getByText("Top 8 · 52.0% of book")).toBeInTheDocument();
    expect(screen.getByText("+2 more")).toBeInTheDocument();

    rerender(
      <PortfolioPanel
        access={adminAccess}
        portfolios={[{ ...samplePortfolio, holdings: {} }]}
        portfolioKey="sample"
        setPortfolioKey={() => {}}
        portfolioMode="sample"
        setPortfolioMode={() => {}}
        customName="Custom book"
        setCustomName={() => {}}
        customRows={[]}
        setCustomRows={() => {}}
        customUnits="weights"
        setCustomUnits={() => {}}
        customBenchmark=""
        setCustomBenchmark={() => {}}
      />
    );
    expect(screen.getByText("No holdings available.")).toBeInTheDocument();
    expect(screen.queryByText(/Top \d/)).not.toBeInTheDocument();
  });

  it("removes any row, including cash, and keeps one blank row editable", () => {
    render(
      <CustomPanelHarness
        initialRows={[
          { id: "row-aapl", ticker: "AAPL", weight: "0.7" },
          { id: "row-cash", ticker: "CASH", weight: "0.3" }
        ]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Remove CASH holding" }));
    expect(screen.queryByDisplayValue("CASH")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Remove AAPL holding" }));
    expect(screen.getByLabelText("Ticker for holding 1")).toHaveValue("");
    expect(screen.getByLabelText("Weight for holding 1")).toHaveValue("");
  });

  it("clears stale validation after row edits, additions, removals, and unit switches", async () => {
    vi.mocked(validatePortfolio).mockResolvedValue(validationResponse(["Stale validation"]));
    render(
      <CustomPanelHarness
        initialRows={[
          { id: "row-aapl", ticker: "AAPL", weight: "0.7" },
          { id: "row-cash", ticker: "CASH", weight: "0.3" }
        ]}
      />
    );

    const validate = async () => {
      fireEvent.click(screen.getByRole("button", { name: "Validate" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("Stale validation");
    };

    await validate();
    fireEvent.change(screen.getByLabelText("Ticker for holding 1"), {
      target: { value: "MSFT" }
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await validate();
    fireEvent.click(screen.getByRole("button", { name: "Add row" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await validate();
    fireEvent.click(screen.getByRole("button", { name: "Remove CASH holding" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await validate();
    fireEvent.click(screen.getByRole("radio", { name: "Shares (MTM)" }));
    fireEvent.click(screen.getByRole("radio", { name: "Weights" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("clears stale validation while an uploaded portfolio is being checked", async () => {
    vi.mocked(validatePortfolio).mockResolvedValueOnce(validationResponse(["Stale validation"]));
    let resolveUpload!: (value: PortfolioValidationResponse) => void;
    vi.mocked(validatePortfolio).mockImplementationOnce(
      () => new Promise((resolve) => (resolveUpload = resolve))
    );
    render(
      <CustomPanelHarness
        initialRows={[{ id: "row-aapl", ticker: "AAPL", weight: "1" }]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Validate" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Stale validation");

    fireEvent.change(screen.getByLabelText("Upload holdings CSV"), {
      target: {
        files: [{ text: async () => "ticker,weight\nMSFT,1" }]
      }
    });
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());

    await act(async () => resolveUpload(validationResponse([])));
  });
});
