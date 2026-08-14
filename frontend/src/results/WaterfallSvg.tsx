import { scaleBand, scaleLinear } from "d3-scale";
import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type FocusEvent,
  type PointerEvent,
  type RefObject
} from "react";
import type { WaterfallData, WaterfallDatum } from "../charts";

interface TooltipState {
  bar: WaterfallDatum;
  x: number;
  y: number;
}

interface ChartMargins {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

const MIN_RENDER_WIDTH = 180;
const MIN_RENDER_HEIGHT = 220;
const TOOLTIP_EDGE_GAP = 8;
const TOOLTIP_MAX_WIDTH = 240;
const PHONE_VALUE_CHARACTER_WIDTH = 7;
const PHONE_VALUE_GAP = 12;
const PHONE_MIN_PLOT_WIDTH = 64;

export function waterfallDomain(waterfall: WaterfallData): [number, number] {
  const values = waterfall.bars.flatMap((bar) => [bar.start, bar.end]);
  const rawMin = Math.min(0, ...values);
  const rawMax = Math.max(0, ...values);
  if (rawMin === rawMax) {
    const extent = waterfall.unit.kind === "percent" ? 0.01 : 1;
    return [-extent, extent];
  }
  const padding = (rawMax - rawMin) * 0.12;
  return [rawMin - padding, rawMax + padding];
}

function useObservedWidth(ref: RefObject<HTMLDivElement>): number {
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = (nextWidth: number): void => {
      if (!Number.isFinite(nextWidth) || nextWidth <= 0) return;
      setWidth((current) => (Math.abs(current - nextWidth) < 0.5 ? current : nextWidth));
    };
    update(element.getBoundingClientRect().width);

    if (typeof ResizeObserver === "undefined") {
      const onResize = (): void => update(element.getBoundingClientRect().width);
      window.addEventListener("resize", onResize);
      return () => window.removeEventListener("resize", onResize);
    }

    const observer = new ResizeObserver((entries) => {
      update(entries[0]?.contentRect.width ?? element.getBoundingClientRect().width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);

  return width;
}

function isRenderable(waterfall: WaterfallData, chartHeight: number): boolean {
  return (
    waterfall.bars.length > 0 &&
    Number.isFinite(chartHeight) &&
    chartHeight >= MIN_RENDER_HEIGHT &&
    waterfall.bars.every((bar) =>
      [bar.value, bar.start, bar.end].every((value) => Number.isFinite(value))
    )
  );
}

function barFill(bar: WaterfallDatum): string {
  if (bar.kind === "total") return "var(--accent-2)";
  if (bar.kind === "residual") return "var(--warn)";
  return bar.value >= 0 ? "var(--up)" : "var(--down)";
}

function formatAxisTick(value: number, waterfall: WaterfallData): string {
  if (waterfall.unit.kind === "percent") {
    return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value * 100)}%`;
  }
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: waterfall.unit.currency,
      notation: "compact",
      maximumFractionDigits: 1
    }).format(value);
  } catch {
    return `${waterfall.unit.currency} ${new Intl.NumberFormat("en-US", {
      notation: "compact",
      maximumFractionDigits: 1
    }).format(value)}`;
  }
}

function truncateLabel(label: string, maxLength: number): string {
  if (label.length <= maxLength) return label;
  return `${label.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…`;
}

function chartMargins(
  width: number,
  isPhone: boolean,
  formattedValues: readonly string[]
): ChartMargins {
  if (isPhone) {
    const left = Math.max(104, Math.min(132, width * 0.34));
    const baselineRight = Math.max(64, Math.min(92, width * 0.23));
    const longestValue = formattedValues.reduce(
      (longest, value) => Math.max(longest, value.length),
      0
    );
    const valueRight = longestValue * PHONE_VALUE_CHARACTER_WIDTH + PHONE_VALUE_GAP;
    const availableRight = Math.max(64, width - left - PHONE_MIN_PLOT_WIDTH);
    return {
      top: 22,
      right: Math.min(Math.max(baselineRight, valueRight), availableRight),
      bottom: 38,
      left
    };
  }
  return { top: 30, right: 22, bottom: 88, left: 62 };
}

function WaterfallFallback({ chartHeight }: { chartHeight: number }) {
  return (
    <div
      className="waterfall-fallback"
      role="status"
      style={{ minHeight: Math.max(MIN_RENDER_HEIGHT, chartHeight) }}
    >
      <strong>Chart unavailable.</strong>
      <span>Use the factor table below for complete attribution details.</span>
    </div>
  );
}

export function WaterfallSvg({
  waterfall,
  chartHeight,
  isPhone
}: {
  waterfall: WaterfallData;
  chartHeight: number;
  isPhone: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const width = useObservedWidth(containerRef);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const titleId = useId();
  const descriptionId = useId();

  if (!isRenderable(waterfall, chartHeight)) {
    return <WaterfallFallback chartHeight={chartHeight} />;
  }

  const showPointerTooltip = (bar: WaterfallDatum, event: PointerEvent<SVGRectElement>): void => {
    const bounds = containerRef.current?.getBoundingClientRect();
    const clientX = Number.isFinite(event.clientX) ? event.clientX : width / 2;
    const clientY = Number.isFinite(event.clientY) ? event.clientY : chartHeight / 2;
    setTooltip({
      bar,
      x: bounds ? clientX - bounds.left : clientX,
      y: bounds ? clientY - bounds.top : clientY
    });
  };

  const showFocusTooltip = (
    bar: WaterfallDatum,
    event: FocusEvent<SVGRectElement>,
    x: number,
    y: number
  ): void => {
    event.currentTarget.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    setTooltip({ bar, x, y });
  };

  const safeWidth = Math.max(MIN_RENDER_WIDTH, width);
  const margins = chartMargins(
    safeWidth,
    isPhone,
    waterfall.bars.map((bar) => bar.formattedValue)
  );
  const domain = waterfallDomain(waterfall);
  const valueScale = scaleLinear()
    .domain(domain)
    .range(
      isPhone
        ? [margins.left, safeWidth - margins.right]
        : [chartHeight - margins.bottom, margins.top]
    )
    .nice(5);
  const categoryScale = scaleBand<string>()
    .domain(waterfall.bars.map((bar) => bar.id))
    .range(
      isPhone
        ? [margins.top, chartHeight - margins.bottom]
        : [margins.left, safeWidth - margins.right]
    )
    .padding(isPhone ? 0.3 : 0.34);
  const ticks = valueScale.ticks(isPhone ? 4 : 5);
  const bandwidth = Math.max(1, categoryScale.bandwidth());
  const axisLabelLength = isPhone ? 18 : Math.max(10, Math.floor(bandwidth / 5.4));

  const tooltipWidth = Math.min(
    TOOLTIP_MAX_WIDTH,
    safeWidth - TOOLTIP_EDGE_GAP * 2
  );
  const tooltipStyle = tooltip
    ? {
        left: Math.max(
          TOOLTIP_EDGE_GAP,
          Math.min(
            safeWidth - tooltipWidth - TOOLTIP_EDGE_GAP,
            tooltip.x + 12
          )
        ),
        top: Math.max(TOOLTIP_EDGE_GAP, Math.min(chartHeight - 78, tooltip.y + 12))
      }
    : undefined;

  return (
    <div
      ref={containerRef}
      className="waterfall-chart"
      data-testid="waterfall-chart"
      style={{ minHeight: chartHeight }}
    >
      {width > 0 ? (
        <svg
          className="waterfall-svg"
          role="group"
          aria-label="Contribution waterfall chart"
          aria-describedby={descriptionId}
          data-orientation={isPhone ? "horizontal" : "vertical"}
          viewBox={`0 0 ${width} ${chartHeight}`}
          width="100%"
          height={chartHeight}
        >
          <title id={titleId}>Contribution waterfall chart</title>
          <desc id={descriptionId}>
            Ordered portfolio P&amp;L contributions followed by the total. Focus a bar for its
            full label and exact value.
          </desc>

          {ticks.map((tick) => {
            const position = valueScale(tick);
            return isPhone ? (
              <g key={`tick:${tick}`} className="waterfall-grid">
                <line
                  x1={position}
                  x2={position}
                  y1={margins.top}
                  y2={chartHeight - margins.bottom}
                  stroke="var(--chart-grid)"
                />
                <text
                  x={position}
                  y={chartHeight - margins.bottom + 20}
                  textAnchor="middle"
                >
                  {formatAxisTick(tick, waterfall)}
                </text>
              </g>
            ) : (
              <g key={`tick:${tick}`} className="waterfall-grid">
                <line
                  x1={margins.left}
                  x2={width - margins.right}
                  y1={position}
                  y2={position}
                  stroke="var(--chart-grid)"
                />
                <text x={margins.left - 9} y={position + 4} textAnchor="end">
                  {formatAxisTick(tick, waterfall)}
                </text>
              </g>
            );
          })}

          {isPhone ? (
            <line
              data-testid="waterfall-zero-line"
              x1={valueScale(0)}
              x2={valueScale(0)}
              y1={margins.top}
              y2={chartHeight - margins.bottom}
              stroke="var(--chart-zero)"
              className="waterfall-zero-line"
            />
          ) : (
            <line
              data-testid="waterfall-zero-line"
              x1={margins.left}
              x2={width - margins.right}
              y1={valueScale(0)}
              y2={valueScale(0)}
              stroke="var(--chart-zero)"
              className="waterfall-zero-line"
            />
          )}

          {waterfall.bars.slice(0, -1).map((bar, index) => {
            const next = waterfall.bars[index + 1];
            const currentPosition = categoryScale(bar.id) ?? 0;
            const nextPosition = categoryScale(next.id) ?? 0;
            return isPhone ? (
              <line
                key={`connector:${bar.id}`}
                data-testid="waterfall-connector"
                x1={valueScale(bar.end)}
                x2={valueScale(bar.end)}
                y1={currentPosition + bandwidth}
                y2={nextPosition}
                stroke="var(--chart-connector)"
                className="waterfall-connector"
              />
            ) : (
              <line
                key={`connector:${bar.id}`}
                data-testid="waterfall-connector"
                x1={currentPosition + bandwidth}
                x2={nextPosition}
                y1={valueScale(bar.end)}
                y2={valueScale(bar.end)}
                stroke="var(--chart-connector)"
                className="waterfall-connector"
              />
            );
          })}

          {waterfall.bars.map((bar) => {
            const categoryPosition = categoryScale(bar.id) ?? 0;
            const start = valueScale(bar.start);
            const end = valueScale(bar.end);
            const x = isPhone ? Math.min(start, end) : categoryPosition;
            const y = isPhone ? categoryPosition : Math.min(start, end);
            const barWidth = isPhone ? Math.max(1, Math.abs(end - start)) : bandwidth;
            const barHeight = isPhone ? bandwidth : Math.max(1, Math.abs(end - start));
            const focusX = isPhone ? end : categoryPosition + bandwidth / 2;
            const focusY = isPhone ? categoryPosition + bandwidth / 2 : end;
            return (
              <g key={bar.id} className={`waterfall-step is-${bar.kind}`}>
                <rect
                  data-waterfall-bar={bar.id}
                  x={x}
                  y={y}
                  width={barWidth}
                  height={barHeight}
                  rx={2}
                  fill={barFill(bar)}
                  tabIndex={0}
                  role="graphics-symbol"
                  aria-label={`${bar.fullLabel}: ${bar.formattedValue}`}
                  onPointerEnter={(event) => showPointerTooltip(bar, event)}
                  onPointerMove={(event) => showPointerTooltip(bar, event)}
                  onPointerLeave={() => setTooltip(null)}
                  onFocus={(event) => showFocusTooltip(bar, event, focusX, focusY)}
                  onBlur={() => setTooltip(null)}
                />
                {isPhone ? (
                  <>
                    <text
                      className="waterfall-category-label"
                      x={margins.left - 9}
                      y={categoryPosition + bandwidth / 2 + 4}
                      textAnchor="end"
                    >
                      {truncateLabel(bar.shortLabel, axisLabelLength)}
                    </text>
                    <text
                      className="waterfall-value-label"
                      x={safeWidth - 4}
                      y={categoryPosition + bandwidth / 2 + 4}
                      textAnchor="end"
                    >
                      {bar.formattedValue}
                    </text>
                  </>
                ) : (
                  <>
                    <text
                      className="waterfall-category-label"
                      x={categoryPosition + bandwidth / 2}
                      y={chartHeight - margins.bottom + 18}
                      textAnchor="end"
                      transform={`rotate(-32 ${categoryPosition + bandwidth / 2} ${
                        chartHeight - margins.bottom + 18
                      })`}
                    >
                      {truncateLabel(bar.shortLabel, axisLabelLength)}
                    </text>
                    <text
                      className="waterfall-value-label"
                      x={categoryPosition + bandwidth / 2}
                      y={end + (bar.value >= 0 ? -7 : 15)}
                      textAnchor="middle"
                    >
                      {bar.formattedValue}
                    </text>
                  </>
                )}
              </g>
            );
          })}
        </svg>
      ) : (
        <div className="skeleton-block waterfall-skeleton" style={{ height: chartHeight }} />
      )}
      {tooltip ? (
        <div className="waterfall-tooltip" role="tooltip" style={tooltipStyle}>
          <strong>{tooltip.bar.fullLabel}</strong>
          <span>{tooltip.bar.formattedValue}</span>
        </div>
      ) : null}
    </div>
  );
}

export default WaterfallSvg;
