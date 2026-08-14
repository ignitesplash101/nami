import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { WaterfallData } from "../charts";
import { WaterfallSvg, waterfallDomain } from "./WaterfallSvg";

const waterfall: WaterfallData = {
  unit: { kind: "percent" },
  bars: [
    {
      id: "factor:SPY",
      shortLabel: "US large-cap (SPY)",
      fullLabel: "US large-cap equities (SPY)",
      value: -0.06,
      start: 0,
      end: -0.06,
      formattedValue: "-6.00%",
      kind: "factor"
    },
    {
      id: "factor:XLK",
      shortLabel: "Technology (XLK)",
      fullLabel: "US technology equities (XLK)",
      value: 0.02,
      start: -0.06,
      end: -0.04,
      formattedValue: "+2.00%",
      kind: "factor"
    },
    {
      id: "total",
      shortLabel: "Total",
      fullLabel: "Total portfolio P&L",
      value: -0.04,
      start: 0,
      end: -0.04,
      formattedValue: "-4.00%",
      kind: "total"
    }
  ]
};

let resizeCallback: ResizeObserverCallback;

function emitResize(width: number): void {
  act(() => {
    resizeCallback(
      [{ contentRect: { width } as DOMRectReadOnly } as ResizeObserverEntry],
      {} as ResizeObserver
    );
  });
}

describe("WaterfallSvg", () => {
  beforeEach(() => {
    class ResizeObserverMock {
      constructor(callback: ResizeObserverCallback) {
        resizeCallback = callback;
      }
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    }
    vi.stubGlobal("ResizeObserver", ResizeObserverMock);
  });

  it("renders a responsive vertical waterfall with cumulative connectors and accessible bars", () => {
    render(<WaterfallSvg waterfall={waterfall} chartHeight={360} isPhone={false} />);
    emitResize(800);

    const svg = screen.getByRole("group", { name: "Contribution waterfall chart" });
    expect(svg).toHaveAttribute("data-orientation", "vertical");
    expect(svg).toHaveAttribute("viewBox", "0 0 800 360");
    expect(screen.getAllByTestId("waterfall-connector")).toHaveLength(2);
    expect(
      screen.getByLabelText("US large-cap equities (SPY): -6.00%")
    ).toHaveAttribute("fill", "var(--down)");
    expect(screen.getByLabelText("Total portfolio P&L: -4.00%")).toHaveAttribute(
      "fill",
      "var(--accent-2)"
    );
    expect(screen.getByTestId("waterfall-zero-line")).toHaveAttribute(
      "stroke",
      "var(--chart-zero)"
    );
  });

  it("renders a true horizontal waterfall on phones", () => {
    render(<WaterfallSvg waterfall={waterfall} chartHeight={360} isPhone />);
    emitResize(360);

    const svg = screen.getByRole("group", { name: "Contribution waterfall chart" });
    expect(svg).toHaveAttribute("data-orientation", "horizontal");
    const firstBar = screen.getByLabelText("US large-cap equities (SPY): -6.00%");
    expect(Number(firstBar.getAttribute("width"))).toBeGreaterThan(0);
    expect(Number(firstBar.getAttribute("height"))).toBeGreaterThan(0);

    const valueLabels = [...document.querySelectorAll(".waterfall-value-label")];
    expect(new Set(valueLabels.map((label) => label.getAttribute("x")))).toHaveLength(1);
    expect(valueLabels.every((label) => label.getAttribute("text-anchor") === "end")).toBe(true);
  });

  it("reserves a phone value column for exact signed dollar labels", () => {
    const formattedValue = "+$1,000,000,000";
    const dollarWaterfall: WaterfallData = {
      unit: { kind: "currency", currency: "USD" },
      bars: [
        {
          id: "factor:large-dollar",
          shortLabel: "Large dollar",
          fullLabel: "Large dollar contribution",
          value: 1_000_000_000,
          start: 0,
          end: 1_000_000_000,
          formattedValue,
          kind: "factor"
        },
        {
          id: "total",
          shortLabel: "Total",
          fullLabel: "Total portfolio P&L",
          value: 1_000_000_000,
          start: 0,
          end: 1_000_000_000,
          formattedValue,
          kind: "total"
        }
      ]
    };
    render(<WaterfallSvg waterfall={dollarWaterfall} chartHeight={360} isPhone />);
    emitResize(320);

    const bar = screen.getByLabelText(`Large dollar contribution: ${formattedValue}`);
    const valueLabel = bar.parentElement?.querySelector(".waterfall-value-label");
    expect(valueLabel).not.toBeNull();
    const barRight = Number(bar.getAttribute("x")) + Number(bar.getAttribute("width"));
    const valueRight = Number(valueLabel?.getAttribute("x"));
    expect(valueRight - barRight).toBeGreaterThanOrEqual(105);
  });

  it("responds to container and fullscreen-height changes", () => {
    const { rerender } = render(
      <WaterfallSvg waterfall={waterfall} chartHeight={360} isPhone={false} />
    );
    emitResize(720);
    expect(screen.getByRole("group", { name: "Contribution waterfall chart" })).toHaveAttribute(
      "viewBox",
      "0 0 720 360"
    );

    emitResize(940);
    rerender(<WaterfallSvg waterfall={waterfall} chartHeight={560} isPhone={false} />);
    expect(screen.getByRole("group", { name: "Contribution waterfall chart" })).toHaveAttribute(
      "viewBox",
      "0 0 940 560"
    );
  });

  it("shows the full label and exact value for pointer and keyboard focus", () => {
    render(<WaterfallSvg waterfall={waterfall} chartHeight={360} isPhone={false} />);
    emitResize(800);
    const bar = screen.getByLabelText("US large-cap equities (SPY): -6.00%");

    fireEvent.pointerEnter(bar, { clientX: 240, clientY: 120 });
    expect(screen.getByRole("tooltip")).toHaveTextContent("US large-cap equities (SPY)");
    expect(screen.getByRole("tooltip")).toHaveTextContent("-6.00%");
    fireEvent.pointerLeave(bar);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    fireEvent.focus(bar);
    expect(screen.getByRole("tooltip")).toHaveTextContent("US large-cap equities (SPY)");
    fireEvent.blur(bar);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("keeps a long pointer tooltip inside a phone-width chart", () => {
    const longLabelWaterfall: WaterfallData = {
      ...waterfall,
      bars: [
        {
          ...waterfall.bars[0],
          fullLabel:
            "An unusually long contribution label that still needs to remain readable on phones"
        },
        waterfall.bars[2]
      ]
    };
    render(<WaterfallSvg waterfall={longLabelWaterfall} chartHeight={360} isPhone />);
    emitResize(320);

    fireEvent.pointerMove(
      screen.getByLabelText(/An unusually long contribution label/),
      { clientX: 319, clientY: 120 }
    );
    const tooltip = screen.getByRole("tooltip");
    expect(Number.parseFloat(tooltip.style.left)).toBeLessThanOrEqual(72);
  });

  it("directs users to the factor table when data is empty or unrenderable", () => {
    const { rerender } = render(
      <WaterfallSvg waterfall={{ bars: [], unit: { kind: "percent" } }} chartHeight={360} isPhone />
    );
    expect(screen.getByRole("status")).toHaveTextContent("factor table");

    rerender(
      <WaterfallSvg
        waterfall={{
          ...waterfall,
          bars: [{ ...waterfall.bars[0], end: Number.NaN }]
        }}
        chartHeight={360}
        isPhone
      />
    );
    expect(screen.getByRole("status")).toHaveTextContent("Chart unavailable");
  });
});

describe("waterfallDomain", () => {
  it("pads positive, negative, and flat data into finite renderable domains", () => {
    const positive = waterfallDomain({
      unit: { kind: "percent" },
      bars: [{ ...waterfall.bars[0], value: 0.1, start: 0, end: 0.1 }]
    });
    const negative = waterfallDomain({
      unit: { kind: "percent" },
      bars: [{ ...waterfall.bars[0], value: -0.1, start: 0, end: -0.1 }]
    });
    const flat = waterfallDomain({
      unit: { kind: "percent" },
      bars: [{ ...waterfall.bars[0], value: 0, start: 0, end: 0 }]
    });

    expect(positive[0]).toBeLessThan(0);
    expect(positive[1]).toBeGreaterThan(0.1);
    expect(negative[0]).toBeLessThan(-0.1);
    expect(negative[1]).toBeGreaterThan(0);
    expect(flat).toEqual([-0.01, 0.01]);
    expect(flat.every(Number.isFinite)).toBe(true);
  });
});
