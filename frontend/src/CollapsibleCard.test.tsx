import { act, fireEvent, render, screen } from "@testing-library/react";
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

  it("renders no fullscreen button when fullscreenable is not set", () => {
    mockMatchMedia(false);
    render(
      <CollapsibleCard title="Factor shocks table">
        <p>table body</p>
      </CollapsibleCard>
    );
    expect(screen.queryByRole("button", { name: /Expand|Collapse/ })).toBeNull();
  });

  it("renders a surface-named fullscreen button when opted in", () => {
    mockMatchMedia(false);
    render(
      <CollapsibleCard title="Factor shocks table" fullscreenable surface="factor shocks">
        <p>table body</p>
      </CollapsibleCard>
    );
    expect(screen.getByRole("button", { name: "Expand factor shocks" })).toBeInTheDocument();
  });

  it("anti-trap: the exit control survives expand -> attempted collapse, an iPhone user has no hardware Esc", () => {
    mockMatchMedia(false); // starts open
    render(
      <CollapsibleCard title="Factor shocks table" fullscreenable surface="factor shocks">
        <p>table body</p>
      </CollapsibleCard>
    );
    const head = screen.getByRole("button", { name: "Factor shocks table" });
    expect(head).toHaveAttribute("aria-expanded", "true");

    // Expand (jsdom has no native Fullscreen API — this drives the
    // expanded-card fallback, the mode with no hardware Esc).
    fireEvent.click(screen.getByRole("button", { name: "Expand factor shocks" }));
    const section = document.querySelector(".collapsible-card") as HTMLElement;
    expect(section.classList.contains("is-card-expanded")).toBe(true);
    expect(screen.getByRole("button", { name: "Collapse factor shocks" })).toBeInTheDocument();

    // Attempt to collapse via the section header while still expanded. If
    // this collapsed the body, the exit button would unmount with it and a
    // touch user would be trapped with no way out.
    fireEvent.click(head);

    // It exited fullscreen instead — the body stayed open, so the exit
    // control (now labeled Expand again) is still present and functional.
    expect(section.classList.contains("is-card-expanded")).toBe(false);
    expect(head).toHaveAttribute("aria-expanded", "true");
    const exitControl = screen.getByRole("button", { name: "Expand factor shocks" });
    expect(exitControl).toBeInTheDocument();

    // Functional: it can re-enter fullscreen.
    fireEvent.click(exitControl);
    expect(section.classList.contains("is-card-expanded")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Collapse factor shocks" }));

    // And exits cleanly — no residual expanded-card state anywhere.
    expect(section.classList.contains("is-card-expanded")).toBe(false);
    expect(document.documentElement.classList.contains("has-expanded-card")).toBe(false);
    expect(document.body.style.overflow).toBe("");

    // Now that fullscreen is exited, the header collapses normally.
    fireEvent.click(head);
    expect(head).toHaveAttribute("aria-expanded", "false");
  });

  it("supports the native fullscreen path when available (button renders, click requests it)", async () => {
    const original = Object.getOwnPropertyDescriptor(document, "fullscreenEnabled");
    Object.defineProperty(document, "fullscreenEnabled", { value: true, configurable: true });
    try {
      mockMatchMedia(false);
      render(
        <CollapsibleCard title="Factor shocks table" fullscreenable surface="factor shocks">
          <p>table body</p>
        </CollapsibleCard>
      );
      const section = document.querySelector(".collapsible-card") as HTMLElement;
      const requestFullscreen = vi.fn().mockResolvedValue(undefined);
      section.requestFullscreen = requestFullscreen;

      const button = screen.getByRole("button", { name: "Expand factor shocks" });
      await act(async () => {
        fireEvent.click(button);
      });
      expect(requestFullscreen).toHaveBeenCalledOnce();
    } finally {
      if (original) {
        Object.defineProperty(document, "fullscreenEnabled", original);
      } else {
        delete (document as { fullscreenEnabled?: boolean }).fullscreenEnabled;
      }
    }
  });
});
