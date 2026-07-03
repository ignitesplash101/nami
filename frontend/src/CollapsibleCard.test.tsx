import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CollapsibleCard } from "./CollapsibleCard";

function mockMatchMedia(compactMatches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: compactMatches,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      onchange: null,
      dispatchEvent: () => false
    }))
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CollapsibleCard", () => {
  it("defaults open on desktop and hides the summary", () => {
    mockMatchMedia(false);
    render(
      <CollapsibleCard title="Factor shocks" summary="19 factors">
        <p>table body</p>
      </CollapsibleCard>
    );
    expect(screen.getByRole("button", { name: /Factor shocks/ })).toHaveAttribute(
      "aria-expanded",
      "true"
    );
    expect(screen.getByText("table body")).toBeVisible();
    expect(screen.queryByText("19 factors")).toBeNull();
  });

  it("defaults collapsed on compact tiers, shows the summary, and toggles open", () => {
    mockMatchMedia(true);
    render(
      <CollapsibleCard title="Factor shocks" summary="19 factors · top SPY -30%">
        <p>table body</p>
      </CollapsibleCard>
    );
    const head = screen.getByRole("button", { name: /Factor shocks/ });
    expect(head).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("19 factors · top SPY -30%")).toBeInTheDocument();
    expect(screen.getByText("table body")).not.toBeVisible(); // mounted but hidden

    fireEvent.click(head);
    expect(head).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("table body")).toBeVisible();
  });

  it("honors an explicit defaultOpen override and shows action only when open", () => {
    mockMatchMedia(false); // desktop would default open…
    render(
      <CollapsibleCard title="Experimental" defaultOpen={false} action={<button>CSV</button>}>
        <p>body</p>
      </CollapsibleCard>
    );
    const head = screen.getByRole("button", { name: /Experimental/ });
    expect(head).toHaveAttribute("aria-expanded", "false"); // …override wins
    expect(screen.queryByRole("button", { name: "CSV" })).toBeNull();
    fireEvent.click(head);
    expect(screen.getByRole("button", { name: "CSV" })).toBeInTheDocument();
  });
});
