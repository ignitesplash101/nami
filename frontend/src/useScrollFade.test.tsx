import { act, fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TableScroll } from "./TableScroll";

function defineSize(node: HTMLElement, scrollWidth: number, clientWidth: number) {
  Object.defineProperty(node, "scrollWidth", { value: scrollWidth, configurable: true });
  Object.defineProperty(node, "clientWidth", { value: clientWidth, configurable: true });
}

describe("TableScroll + useScrollFade", () => {
  it("renders without the fade when nothing overflows (jsdom default)", () => {
    const { container } = render(
      <TableScroll>
        <table />
      </TableScroll>
    );
    const wrap = container.querySelector(".table-wrap")!;
    expect(wrap).not.toHaveClass("has-overflow");
    expect(container.querySelector(".table-wrap > .table-scroll")).not.toBeNull();
  });

  it("shows the fade only while hidden content remains to the right", () => {
    const { container } = render(
      <TableScroll>
        <table />
      </TableScroll>
    );
    const wrap = container.querySelector(".table-wrap")!;
    const scroller = container.querySelector<HTMLElement>(".table-scroll")!;

    // Content wider than the viewport — fade appears on the next measure.
    defineSize(scroller, 800, 400);
    act(() => {
      fireEvent.scroll(scroller);
    });
    expect(wrap).toHaveClass("has-overflow");

    // Scrolled to the end — fade hides (nothing left to reveal).
    scroller.scrollLeft = 400;
    act(() => {
      fireEvent.scroll(scroller);
    });
    expect(wrap).not.toHaveClass("has-overflow");
  });
});
