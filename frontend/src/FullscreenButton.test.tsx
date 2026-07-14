import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FullscreenButton } from "./FullscreenButton";

describe("FullscreenButton", () => {
  it("still renders (Expand label) when native fullscreen is unsupported — the fallback is universal", () => {
    render(
      <FullscreenButton
        controller={{ isFullscreen: false, toggle: () => {}, supported: false }}
        surface="contribution waterfall"
      />
    );
    expect(
      screen.getByRole("button", { name: "Expand contribution waterfall" })
    ).toBeInTheDocument();
  });

  it("labels the affordance Expand {surface} when not fullscreen", () => {
    render(
      <FullscreenButton
        controller={{ isFullscreen: false, toggle: () => {}, supported: true }}
        surface="contribution waterfall"
      />
    );
    const button = screen.getByRole("button", { name: "Expand contribution waterfall" });
    expect(button).toHaveAttribute("title", "Expand contribution waterfall");
  });

  it("labels the affordance Collapse {surface} when fullscreen", () => {
    render(
      <FullscreenButton
        controller={{ isFullscreen: true, toggle: () => {}, supported: true }}
        surface="diagnostics waterfall"
      />
    );
    const button = screen.getByRole("button", { name: "Collapse diagnostics waterfall" });
    expect(button).toHaveAttribute("title", "Collapse diagnostics waterfall");
  });

  it("calls toggle on click", () => {
    const toggle = vi.fn();
    render(
      <FullscreenButton
        controller={{ isFullscreen: false, toggle, supported: true }}
        surface="contribution waterfall"
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Expand contribution waterfall" }));
    expect(toggle).toHaveBeenCalledOnce();
  });
});
