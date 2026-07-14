import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { ChoiceGroup } from "./ChoiceGroup";

type Choice = "alpha" | "beta" | "gamma";

function Harness() {
  const [value, setValue] = useState<Choice>("alpha");
  return (
    <ChoiceGroup
      ariaLabel="Demo choices"
      className="segmented"
      value={value}
      onChange={setValue}
      options={[
        { key: "alpha", label: "Alpha" },
        { key: "beta", label: "Beta", disabled: true },
        { key: "gamma", label: "Gamma" }
      ]}
    />
  );
}

describe("ChoiceGroup", () => {
  it("uses radio semantics and a single roving tab stop", () => {
    render(<Harness />);

    expect(screen.getByRole("radiogroup", { name: "Demo choices" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Alpha" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Alpha" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("radio", { name: "Gamma" })).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("radio", { name: "Beta" })).toBeDisabled();
  });

  it("automatically selects and focuses with arrows, wrapping past disabled options", () => {
    render(<Harness />);
    const alpha = screen.getByRole("radio", { name: "Alpha" });
    const gamma = screen.getByRole("radio", { name: "Gamma" });
    alpha.focus();

    fireEvent.keyDown(alpha, { key: "ArrowRight" });
    expect(gamma).toHaveAttribute("aria-checked", "true");
    expect(gamma).toHaveFocus();

    fireEvent.keyDown(gamma, { key: "ArrowDown" });
    expect(alpha).toHaveAttribute("aria-checked", "true");
    expect(alpha).toHaveFocus();

    fireEvent.keyDown(alpha, { key: "ArrowUp" });
    expect(gamma).toHaveAttribute("aria-checked", "true");
    expect(gamma).toHaveFocus();
  });

  it("supports Home, End, and click without landing on disabled choices", () => {
    render(<Harness />);
    const alpha = screen.getByRole("radio", { name: "Alpha" });
    const gamma = screen.getByRole("radio", { name: "Gamma" });

    fireEvent.keyDown(alpha, { key: "End" });
    expect(gamma).toHaveAttribute("aria-checked", "true");
    expect(gamma).toHaveFocus();

    fireEvent.keyDown(gamma, { key: "Home" });
    expect(alpha).toHaveAttribute("aria-checked", "true");
    expect(alpha).toHaveFocus();

    fireEvent.click(gamma);
    expect(gamma).toHaveAttribute("aria-checked", "true");
  });
});
