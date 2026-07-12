import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScenarioWorkspace } from "./ScenarioWorkspace";

describe("ScenarioWorkspace", () => {
  it("marks first-run and completed-result layouts without changing content order", () => {
    const { rerender } = render(
      <ScenarioWorkspace
        hasResults={false}
        input={<section aria-label="Scenario input">Input</section>}
        output={<section aria-label="Scenario output">Output</section>}
      />
    );

    const workspace = screen.getByLabelText("Scenario workspace");
    const input = screen.getByLabelText("Scenario input");
    const output = screen.getByLabelText("Scenario output");

    expect(workspace).toHaveClass("scenario-workspace", "is-first-run");
    expect(input.compareDocumentPosition(output) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    rerender(
      <ScenarioWorkspace
        hasResults
        input={<section aria-label="Scenario input">Input</section>}
        output={<section aria-label="Scenario output">Output</section>}
      />
    );

    expect(screen.getByLabelText("Scenario workspace")).toHaveClass("has-results");
    expect(screen.getByLabelText("Scenario workspace")).not.toHaveClass("is-first-run");
  });
});
