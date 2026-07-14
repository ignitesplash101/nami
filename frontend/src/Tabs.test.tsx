import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Tabs } from "./Tabs";
import type { TabItem } from "./Tabs";

type Key = "one" | "two" | "three";

const ITEMS: TabItem<Key>[] = [
  { key: "one", label: "One", content: <p>first panel</p> },
  { key: "two", label: "Two", content: <p>second panel</p> },
  { key: "three", label: "Three", content: <p>third panel</p> }
];

function Harness() {
  const [active, setActive] = useState<Key>("one");
  return (
    <Tabs items={ITEMS} active={active} onChange={setActive} ariaLabel="Demo tabs" idBase="demo" />
  );
}

describe("Tabs", () => {
  it("wires tablist/tab/tabpanel roles with aria-controls and roving tabIndex", () => {
    render(<Harness />);
    expect(screen.getByRole("tablist", { name: "Demo tabs" })).toBeInTheDocument();
    const one = screen.getByRole("tab", { name: "One" });
    const two = screen.getByRole("tab", { name: "Two" });
    expect(one).toHaveAttribute("aria-selected", "true");
    expect(one).toHaveAttribute("aria-controls", "demo-panel-one");
    expect(one).toHaveAttribute("tabindex", "0");
    expect(two).toHaveAttribute("tabindex", "-1");
  });

  it("keeps inactive panels MOUNTED but hidden so child state survives", () => {
    render(<Harness />);
    // hidden content stays in the DOM (queryable by text, absent from a11y tree)
    expect(screen.getByText("second panel")).toBeInTheDocument();
    const panelTwo = document.getElementById("demo-panel-two");
    expect(panelTwo).toHaveAttribute("hidden");
    fireEvent.click(screen.getByRole("tab", { name: "Two" }));
    expect(panelTwo).not.toHaveAttribute("hidden");
    expect(document.getElementById("demo-panel-one")).toHaveAttribute("hidden");
  });

  it("moves, selects, and focuses with arrow keys (automatic activation), wrapping at ends", () => {
    render(<Harness />);
    const one = screen.getByRole("tab", { name: "One" });
    const two = screen.getByRole("tab", { name: "Two" });
    const three = screen.getByRole("tab", { name: "Three" });
    one.focus();

    fireEvent.keyDown(one, { key: "ArrowRight" });
    expect(two).toHaveAttribute("aria-selected", "true");
    expect(two).toHaveFocus();

    fireEvent.keyDown(two, { key: "ArrowLeft" });
    fireEvent.keyDown(one, { key: "ArrowLeft" });
    expect(three).toHaveAttribute("aria-selected", "true");
    expect(three).toHaveFocus();

    fireEvent.keyDown(three, { key: "Home" });
    expect(one).toHaveAttribute("aria-selected", "true");
    expect(one).toHaveFocus();

    fireEvent.keyDown(one, { key: "End" });
    expect(three).toHaveAttribute("aria-selected", "true");
    expect(three).toHaveFocus();
  });

  it("renders a decorative busy dot on items flagged busy, without changing the accessible name", () => {
    const items: TabItem<Key>[] = [
      { key: "one", label: "One", content: <p>first panel</p>, busy: true },
      { key: "two", label: "Two", content: <p>second panel</p> }
    ];
    render(
      <Tabs items={items} active="one" onChange={() => {}} ariaLabel="Demo tabs" idBase="demo" />
    );

    // Exact previous accessible name still resolves — the dot is aria-hidden
    // and appended after the label, so it never enters the accname.
    const busyTab = screen.getByRole("tab", { name: "One" });
    const dot = busyTab.querySelector(".tab-busy-dot");
    expect(dot).toBeInTheDocument();
    expect(dot).toHaveAttribute("aria-hidden", "true");

    const idleTab = screen.getByRole("tab", { name: "Two" });
    expect(idleTab.querySelector(".tab-busy-dot")).not.toBeInTheDocument();
  });
});
