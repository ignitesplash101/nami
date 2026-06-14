import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AccessResponse } from "./types";

function AccessSummary({ access }: { access: AccessResponse }) {
  return (
    <div>
      <span>{access.access_mode}</span>
      {access.permissions.free_text_scenario ? <button>Custom scenario</button> : null}
      {access.permissions.custom_portfolio ? <button>Upload portfolio</button> : null}
      {access.permissions.narrative_decomposition ? <button>Run theme sensitivity</button> : null}
    </div>
  );
}

describe("access-gated UI controls", () => {
  it("hides unrestricted controls from visitors", () => {
    render(
      <AccessSummary
        access={{
          access_mode: "visitor",
          admin_available: true,
          latest_market_date: "2026-05-28",
          permissions: {
            custom_portfolio: false,
            free_text_scenario: false,
            narrative_decomposition: false
          }
        }}
      />
    );

    expect(screen.queryByText("Custom scenario")).not.toBeInTheDocument();
    expect(screen.queryByText("Upload portfolio")).not.toBeInTheDocument();
    expect(screen.queryByText("Run theme sensitivity")).not.toBeInTheDocument();
  });

  it("shows unrestricted controls to admins", () => {
    render(
      <AccessSummary
        access={{
          access_mode: "admin",
          admin_available: true,
          latest_market_date: "2026-05-28",
          permissions: {
            custom_portfolio: true,
            free_text_scenario: true,
            narrative_decomposition: true
          }
        }}
      />
    );

    expect(screen.getByText("Custom scenario")).toBeInTheDocument();
    expect(screen.getByText("Upload portfolio")).toBeInTheDocument();
    expect(screen.getByText("Run theme sensitivity")).toBeInTheDocument();
  });
});
