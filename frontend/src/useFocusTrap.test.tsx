import { render } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it } from "vitest";
import { useFocusTrap } from "./useFocusTrap";

function TrapHarness({ active }: { active: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref, active);
  return (
    <div ref={ref}>
      <button data-testid="first">First</button>
      <button data-testid="middle">Middle</button>
      <button data-testid="last">Last</button>
    </div>
  );
}

function pressTab(shiftKey = false) {
  document.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Tab", shiftKey, bubbles: true, cancelable: true })
  );
}

describe("useFocusTrap", () => {
  it("wraps Tab from the last focusable back to the first", () => {
    const { getByTestId } = render(<TrapHarness active />);
    getByTestId("last").focus();
    pressTab();
    expect(document.activeElement).toBe(getByTestId("first"));
  });

  it("wraps Shift+Tab from the first focusable to the last", () => {
    const { getByTestId } = render(<TrapHarness active />);
    getByTestId("first").focus();
    pressTab(true);
    expect(document.activeElement).toBe(getByTestId("last"));
  });

  it("does not trap when inactive", () => {
    const { getByTestId } = render(<TrapHarness active={false} />);
    const last = getByTestId("last");
    last.focus();
    pressTab();
    // No trap installed and jsdom has no native Tab handling, so focus stays put.
    expect(document.activeElement).toBe(last);
  });

  it("does not throw when there are no focusable elements", () => {
    function Empty() {
      const ref = useRef<HTMLDivElement>(null);
      useFocusTrap(ref, true);
      return <div ref={ref} />;
    }
    expect(() => {
      render(<Empty />);
      pressTab();
    }).not.toThrow();
  });
});
