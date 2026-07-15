import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RunProgress, stageLabel } from "./RunProgress";

describe("RunProgress", () => {
  it("marks the active stage with aria-current=step", () => {
    render(
      <RunProgress
        currentStage="betas"
        stageStatus="start"
        completedStages={new Set(["cache_check", "market"])}
        cacheHit={false}
      />
    );
    const active = screen.getByText("Estimating factor betas").closest("li");
    expect(active).toHaveAttribute("aria-current", "step");
    const done = screen.getByText("Fetching market data").closest("li");
    expect(done).not.toHaveAttribute("aria-current");
  });

  it("stageLabel maps pipeline stages and null-safes terminal events", () => {
    expect(stageLabel("narrative")).toBe("Grounding narrative (Google Search)");
    expect(stageLabel("done")).toBeNull();
    expect(stageLabel("error")).toBeNull();
  });

  it("uses the shorter ordered Quant V2 stages without legacy-only work", () => {
    render(
      <RunProgress
        currentStage="attribution"
        stageStatus="start"
        completedStages={new Set(["cache_check", "market", "analogs"])}
        cacheHit={false}
        engineMode="quant_v2"
      />
    );

    expect(screen.getByText("Building historical model").closest("li")).toHaveAttribute(
      "aria-current",
      "step"
    );
    expect(screen.queryByText("Computing analog envelope")).not.toBeInTheDocument();
    expect(screen.queryByText("Estimating factor betas")).not.toBeInTheDocument();
    expect(stageLabel("narrative", "quant_v2")).toBe("Writing scenario explanation");
  });
});
