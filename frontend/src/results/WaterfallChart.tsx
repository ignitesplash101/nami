import { lazy, Suspense } from "react";
import type { WaterfallData } from "../charts";

const WaterfallSvg = lazy(() => import("./WaterfallSvg"));

/** Lazy boundary for the results-only chart path. The implementation owns the
 * responsive SVG and interaction; this shell keeps all chart geometry out of
 * the first-screen dependency graph. */
export function WaterfallChart({
  waterfall,
  chartHeight,
  isPhone
}: {
  waterfall: WaterfallData;
  chartHeight: number;
  isPhone: boolean;
}) {
  return (
    <Suspense
      fallback={<div className="skeleton-block waterfall-skeleton" style={{ height: chartHeight }} />}
    >
      <WaterfallSvg waterfall={waterfall} chartHeight={chartHeight} isPhone={isPhone} />
    </Suspense>
  );
}
