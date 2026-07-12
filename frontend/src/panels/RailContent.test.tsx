import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RailContent } from "./RailContent";
import type { AccessResponse } from "../types";

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

describe("RailContent", () => {
  it("keeps an operations-console path in the compact rail", () => {
    const onOpenOperations = vi.fn();
    render(
      <RailContent
        access={adminAccess}
        onAccessChange={() => {}}
        portfolios={[]}
        portfolioKey=""
        setPortfolioKey={() => {}}
        portfolioMode="sample"
        setPortfolioMode={() => {}}
        customName="Custom Book"
        setCustomName={() => {}}
        customRows={[]}
        setCustomRows={() => {}}
        customUnits="weights"
        setCustomUnits={() => {}}
        customBenchmark=""
        setCustomBenchmark={() => {}}
        onOpenOperations={onOpenOperations}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Open operations console" }));
    expect(onOpenOperations).toHaveBeenCalledTimes(1);
  });
});
