import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { InfoTip } from "./InfoTip";
import { GLOSSARY } from "./glossary";

describe("InfoTip", () => {
  it("toggles an anchored note with aria-expanded", () => {
    render(<InfoTip label="About single-name noise">explains the band</InfoTip>);
    const btn = screen.getByRole("button", { name: "About single-name noise" });
    expect(btn).toHaveAttribute("aria-expanded", "false");
    const popoverId = btn.getAttribute("aria-controls");
    expect(popoverId).toBeTruthy();
    expect(screen.queryByRole("note")).toBeNull();

    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("note")).toHaveAttribute("id", popoverId);
    expect(screen.getByRole("note")).toHaveTextContent("explains the band");

    fireEvent.click(btn);
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("closes on outside pointerdown and on Escape", () => {
    render(
      <div>
        <InfoTip label="tip">content</InfoTip>
        <button>outside</button>
      </div>
    );
    const btn = screen.getByRole("button", { name: "tip" });

    fireEvent.click(btn);
    fireEvent.pointerDown(screen.getByRole("button", { name: "outside" }));
    expect(screen.queryByRole("note")).toBeNull();

    fireEvent.click(btn);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("note")).toBeNull();
  });
});

describe("glossary", () => {
  it("keeps every entry plain-first with a term", () => {
    for (const entry of Object.values(GLOSSARY)) {
      expect(entry.term.length).toBeGreaterThan(0);
      expect(entry.plain.length).toBeGreaterThan(20);
    }
  });

  it("carries the idio-band honesty caveat VERBATIM in the detail layer", () => {
    expect(GLOSSARY.singleNameNoise.detail).toContain(
      "A dispersion floor under independence assumptions — not a confidence interval on the scenario."
    );
  });
});
