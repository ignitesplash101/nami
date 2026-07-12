import type { ReactNode } from "react";

export function ScenarioWorkspace({
  hasResults,
  input,
  output
}: {
  hasResults: boolean;
  input: ReactNode;
  output: ReactNode;
}) {
  return (
    <section
      className={`scenario-workspace ${hasResults ? "has-results" : "is-first-run"}`}
      aria-label="Scenario workspace"
    >
      <div className="scenario-input-column">{input}</div>
      <div className="scenario-output-column">{output}</div>
    </section>
  );
}
